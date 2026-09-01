import { useState } from 'react';

import { useSettings, useUpdateSettings } from '@/api/queries';
import type { Settings, SettingsUpdate } from '@/api/types';
import { Field, Notice, SectionLabel } from '@/components/ui';

/**
 * GitHub access (§4.3).
 *
 * The PAT field is **write-only**: the API only ever reports `pat_set`, and
 * nothing here reads, stores or renders a token. The input starts empty on
 * every visit, and submitting it empty leaves whatever is stored untouched.
 */
export function SettingsScreen() {
  const settings = useSettings();
  const update = useUpdateSettings();

  const [pat, setPat] = useState('');
  const [apiVersion, setApiVersion] = useState('');
  const [apiBase, setApiBase] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);

  /**
   * Seed the advanced fields from whatever the server last returned, and re-seed
   * whenever that value actually changes. Adjusting state during render (the
   * React docs' "derived state" pattern) rather than in an effect: an effect
   * would paint one frame with the stale values first, which is what
   * `react-hooks/set-state-in-effect` flags.
   */
  const [seededFrom, setSeededFrom] = useState<Settings | undefined>(undefined);
  if (settings.data && settings.data !== seededFrom) {
    setSeededFrom(settings.data);
    setApiVersion(settings.data.github_api_version);
    setApiBase(settings.data.github_api_base);
  }

  const submit = (event: React.SyntheticEvent) => {
    event.preventDefault();
    const body: SettingsUpdate = {};
    if (pat.trim()) body.github_pat = pat.trim();
    if (apiVersion.trim() && apiVersion.trim() !== settings.data?.github_api_version) {
      body.github_api_version = apiVersion.trim();
    }
    if (apiBase.trim() && apiBase.trim() !== settings.data?.github_api_base) {
      body.github_api_base = apiBase.trim();
    }
    if (Object.keys(body).length === 0) return;
    update.mutate(body, {
      onSuccess: () => {
        setPat('');
      },
    });
  };

  const dirty =
    pat.trim().length > 0 ||
    (settings.data !== undefined &&
      (apiVersion.trim() !== settings.data.github_api_version ||
        apiBase.trim() !== settings.data.github_api_base));

  return (
    <div className="h-full overflow-y-auto px-[26px] pt-[44px] pb-[60px]">
      <div className="max-w-[620px]">
        <h1 className="font-heading m-0 mb-[12px] text-[42px] leading-[1.06] tracking-[-0.015em]">
          GitHub access
        </h1>
        <p className="m-0 mb-[30px] max-w-[46ch] text-[16px] leading-[1.5] text-neutral-800">
          Calleegraph only ever reads workflow files. The token is encrypted at rest, never returned
          by the API and never shown here — only whether one is stored.
        </p>

        <form className="flex flex-col gap-[20px]" onSubmit={submit}>
          <div>
            <SectionLabel>Status</SectionLabel>
            <p className="m-0 text-[14px] leading-[1.5]">
              {settings.isPending && 'Loading…'}
              {settings.data?.pat_set === true && (
                <>
                  A token is stored
                  {settings.data.github_actor_login ? (
                    <>
                      {' '}
                      and authenticates as{' '}
                      <span className="cg-mono">{settings.data.github_actor_login}</span>
                    </>
                  ) : null}
                  . Enter a new one below to replace it.
                </>
              )}
              {settings.data?.pat_set === false &&
                'No token stored. Public repositories work without one, at much lower rate limits.'}
            </p>
          </div>

          <Field
            id="github-pat"
            label="Personal access token"
            hint={
              <>
                Needs <span className="cg-mono">contents:read</span> (classic:{' '}
                <span className="cg-mono">repo</span>) to read private repositories. Leave blank to
                keep the stored token.
              </>
            }
          >
            <input
              id="github-pat"
              className="input cg-mono text-[13px]"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={
                settings.data?.pat_set ? 'Stored — enter a new token to replace' : 'ghp_…'
              }
              value={pat}
              onChange={(event) => {
                setPat(event.target.value);
              }}
            />
          </Field>

          <div>
            <button
              type="button"
              className="btn btn-ghost px-0 text-[12.5px]"
              aria-expanded={advancedOpen}
              onClick={() => {
                setAdvancedOpen((open) => !open);
              }}
            >
              {advancedOpen ? '– Advanced' : '+ Advanced (GitHub Enterprise)'}
            </button>
            {advancedOpen && (
              <div className="mt-[14px] flex flex-col gap-[16px]">
                <Field id="github-api-version" label="API version">
                  <input
                    id="github-api-version"
                    className="input cg-mono text-[13px]"
                    value={apiVersion}
                    spellCheck={false}
                    onChange={(event) => {
                      setApiVersion(event.target.value);
                    }}
                  />
                </Field>
                <Field
                  id="github-api-base"
                  label="API base URL"
                  hint="For GitHub Enterprise, e.g. https://github.example.com/api/v3"
                >
                  <input
                    id="github-api-base"
                    className="input cg-mono text-[13px]"
                    value={apiBase}
                    spellCheck={false}
                    onChange={(event) => {
                      setApiBase(event.target.value);
                    }}
                  />
                </Field>
              </div>
            )}
          </div>

          {update.isError && <Notice tone="problem">{update.error.message}</Notice>}
          {update.isSuccess && !dirty && (
            <Notice tone="info">
              {update.data.pat_set
                ? update.data.github_actor_login
                  ? `Saved — the token authenticates as ${update.data.github_actor_login}.`
                  : 'Saved.'
                : 'Saved.'}
            </Notice>
          )}

          <div>
            <button
              type="submit"
              className="btn btn-primary text-[14px]"
              disabled={!dirty || update.isPending}
            >
              {update.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
