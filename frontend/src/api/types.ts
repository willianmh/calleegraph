/**
 * The shared API contract, transcribed verbatim from the authoritative
 * source: `03_orchestrator_prompt.md` §5. Do not "improve" a shape here —
 * if the backend and this file disagree, §5 wins and the drift is reported
 * to the orchestrator rather than patched locally.
 */

export type RepoStatus = 'pending' | 'fetching' | 'parsing' | 'done' | 'error';
export type NodeKind = 'top_level' | 'reusable';
export type IOType = 'string' | 'boolean' | 'number' | 'choice';
export type EdgeStatus = 'ok' | 'warning' | 'error' | 'unresolved';
export type IssueSeverity = 'error' | 'warning';
export type IssueCode =
  | 'unknown_input'
  | 'missing_required_input'
  | 'type_mismatch'
  | 'unresolvable_condition'
  | 'unresolved_target';

export interface Repository {
  id: number;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  status: RepoStatus;
  error: string | null;
  last_synced_commit_sha: string | null;
  last_synced_at: string | null;
  created_at: string;
}

export interface WorkflowIODef {
  name: string;
  type: IOType;
  required: boolean;
  default: string | boolean | number | null;
  description: string | null;
  options: string[] | null;
}

export interface JobCall {
  target_node_id: string | null;
  target_ref: string;
  with: Record<string, string>;
  secrets_mode: 'inherit' | 'explicit' | 'none';
  secrets: string[] | null;
}

export interface JobNode {
  id: string;
  job_key: string;
  name: string | null;
  needs: string[];
  condition: string | null;
  call: JobCall | null;
}

export interface WorkflowNode {
  id: string;
  repository_full_name: string;
  path: string;
  name: string;
  kind: NodeKind;
  triggers: string[];
  jobs: JobNode[];
  declared_inputs: WorkflowIODef[];
  declared_secrets: string[];
  declared_outputs: WorkflowIODef[];
}

export interface EdgeIssue {
  severity: IssueSeverity;
  code: IssueCode;
  /** Plain-language description. Rendered verbatim — never paraphrased. */
  message: string;
  /** Actionable fix. Rendered verbatim — never invented client-side. */
  suggestion: string | null;
  input_name: string | null;
}

export interface Edge {
  id: string;
  source_node_id: string;
  source_job_id: string;
  target_node_id: string | null;
  target_ref: string;
  condition: string | null;
  status: EdgeStatus;
  issues: EdgeIssue[];
}

export interface GraphResponse {
  repositories: Repository[];
  nodes: WorkflowNode[];
  edges: Edge[];
  generated_at: string;
}

export interface Settings {
  pat_set: boolean;
  github_actor_login: string | null;
  github_api_version: string;
  github_api_base: string;
}

export interface SettingsUpdate {
  github_pat?: string;
  github_api_version?: string;
  github_api_base?: string;
}

export interface HealthResponse {
  status: string;
  db: string;
  cache: string;
}
