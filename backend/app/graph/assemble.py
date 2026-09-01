"""Builds the ``GraphResponse`` from DB rows (backend prompt §11).

Resolution (§8) and validation (§9) are recomputed here on every assembly
rather than read from the database — that is what keeps a cross-repo edge
correct after the *other* repo is added or removed, without re-syncing either.
"""

from __future__ import annotations

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.graph.resolve import RepoRefState, resolve_call
from app.graph.validate import (
    check_condition,
    edge_status,
    unresolved_target_issue,
    validate_call,
)
from app.models import Job, JobCall, Repository, WorkflowNode, utcnow
from app.schemas import Edge, EdgeIssue, GraphResponse, JobNode, RepositoryResponse
from app.schemas import JobCall as JobCallSchema
from app.schemas import WorkflowIODef as WorkflowIODefSchema
from app.schemas import WorkflowNode as WorkflowNodeSchema


def repository_to_schema(repo: Repository) -> RepositoryResponse:
    assert repo.id is not None
    return RepositoryResponse(
        id=repo.id,
        owner=repo.owner,
        name=repo.name,
        full_name=repo.full_name,
        default_branch=repo.default_branch,
        status=repo.status.value,  # type: ignore[arg-type]
        error=repo.error,
        last_synced_commit_sha=repo.last_synced_commit_sha,
        last_synced_at=repo.last_synced_at,
        created_at=repo.created_at,
    )


def _io_defs(raw: list[dict[str, object]]) -> list[WorkflowIODefSchema]:
    defs: list[WorkflowIODefSchema] = []
    for item in raw:
        try:
            defs.append(WorkflowIODefSchema.model_validate(item))
        except Exception:  # noqa: BLE001 - a bad stored row must not break the graph
            continue
    return defs


def _edge_id(source_job_id: str, target_ref: str) -> str:
    """Stable across re-syncs of the same commit SHA (contract invariant §5).

    Built only from ``source_job_id`` (itself repo/path/job_key) and the raw
    `uses:` string — no counters, no row ids, and deliberately *not* the
    resolved target. That keeps the id stable when an edge flips between
    `unresolved` and resolved because another repo was added or removed, so
    the frontend can animate that transition instead of swapping one edge for
    a different one.
    """
    return f"{source_job_id}->{target_ref}"


async def assemble_graph(session: AsyncSession) -> GraphResponse:
    """Load all rows, resolve, validate, and build the combined graph."""
    repos = (await session.exec(select(Repository).order_by(col(Repository.id)))).all()
    repo_by_id = {r.id: r for r in repos}

    # Only repos with a synced commit contribute nodes; pending/fetching/parsing
    # repos still appear in `repositories` with their current status (§11).
    synced_repo_ids = {r.id for r in repos if r.last_synced_commit_sha}

    node_rows = (
        await session.exec(select(WorkflowNode).order_by(WorkflowNode.id))
    ).all()
    node_rows = [n for n in node_rows if n.repository_id in synced_repo_ids]
    node_by_id = {n.id: n for n in node_rows}

    job_rows = (await session.exec(select(Job).order_by(Job.id))).all()
    job_rows = [j for j in job_rows if j.workflow_node_id in node_by_id]
    jobs_by_node: dict[str, list[Job]] = {}
    for job in job_rows:
        jobs_by_node.setdefault(job.workflow_node_id, []).append(job)

    call_rows = (await session.exec(select(JobCall))).all()
    job_ids = {j.id for j in job_rows}
    call_by_job_id = {c.job_id: c for c in call_rows if c.job_id in job_ids}

    repo_states = {
        r.full_name: RepoRefState(
            full_name=r.full_name,
            default_branch=r.default_branch,
            last_synced_commit_sha=r.last_synced_commit_sha,
        )
        for r in repos
    }
    known_node_ids = set(node_by_id)

    nodes: list[WorkflowNodeSchema] = []
    edges: list[Edge] = []

    for node in node_rows:
        repo = repo_by_id[node.repository_id]
        node_jobs = jobs_by_node.get(node.id, [])
        sibling_job_keys = {j.job_key for j in node_jobs}
        declared_inputs = _io_defs(node.declared_inputs)
        own_input_names = {d.name for d in declared_inputs}
        # `inputs.x` in an `if:` is only checkable against `declared_inputs`
        # when this workflow is reusable. A workflow that is *also*
        # `workflow_dispatch`-triggered has a second, unmodelled input source,
        # so we skip the check there rather than emit a false positive (§9).
        check_inputs = node.kind.value == "reusable" and "workflow_dispatch" not in node.triggers

        job_schemas: list[JobNode] = []
        for job in node_jobs:
            call = call_by_job_id.get(job.id)
            call_schema: JobCallSchema | None = None
            if call is not None:
                resolution = resolve_call(
                    call.target_ref,
                    source_repo_full_name=repo.full_name,
                    repo_states=repo_states,
                    known_node_ids=known_node_ids,
                )
                target_node_id = resolution.node_id
                call_schema = JobCallSchema(
                    target_node_id=target_node_id,
                    target_ref=call.target_ref,
                    with_mapping=call.with_mapping,
                    secrets_mode=call.secrets_mode.value,  # type: ignore[arg-type]
                    secrets=call.secrets,
                )

                issues: list[EdgeIssue] = []
                if target_node_id is not None:
                    callee = node_by_id[target_node_id]
                    issues = validate_call(call.with_mapping, _io_defs(callee.declared_inputs))
                    issues += check_condition(
                        job.condition,
                        sibling_job_keys=sibling_job_keys,
                        own_declared_input_names=own_input_names,
                        check_inputs=check_inputs,
                    )
                else:
                    # Exactly one issue, explaining the unresolved state itself.
                    # No input-wiring rules run here: there is no parsed callee
                    # to check `with:` against (§9).
                    issues = [unresolved_target_issue(resolution)]
                edges.append(
                    Edge(
                        id=_edge_id(job.id, call.target_ref),
                        source_node_id=node.id,
                        source_job_id=job.id,
                        target_node_id=target_node_id,
                        target_ref=call.target_ref,
                        condition=job.condition,
                        status=edge_status(target_node_id is not None, issues),
                        issues=issues,
                    )
                )

            job_schemas.append(
                JobNode(
                    id=job.id,
                    job_key=job.job_key,
                    name=job.name,
                    needs=job.needs,
                    condition=job.condition,
                    call=call_schema,
                )
            )

        job_schemas.sort(key=lambda j: j.id)
        nodes.append(
            WorkflowNodeSchema(
                id=node.id,
                repository_full_name=repo.full_name,
                path=node.path,
                name=node.name,
                kind=node.kind.value,  # type: ignore[arg-type]
                triggers=node.triggers,
                jobs=job_schemas,
                declared_inputs=declared_inputs,
                declared_secrets=node.declared_secrets,
                declared_outputs=_io_defs(node.declared_outputs),
            )
        )

    nodes.sort(key=lambda n: n.id)
    edges.sort(key=lambda e: e.id)

    return GraphResponse(
        repositories=[repository_to_schema(r) for r in repos],
        nodes=nodes,
        edges=edges,
        generated_at=utcnow(),
    )
