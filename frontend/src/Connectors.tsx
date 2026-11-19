/** Connectors: switch on ready-made MCP tools, add custom servers, and approve outward actions. */

import { clsx } from "clsx";
import {
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  HardDrive,
  Hash,
  Paperclip,
  Plug,
  RefreshCw,
  Settings2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  type Connector,
  type ConnectorAction,
  addCustomConnector,
  connectConnector,
  decideConnectorAction,
  disconnectConnector,
  listConnectors,
  testConnector,
  updateConnector,
} from "./api";
import { Badge, Button, IconButton } from "./ui";

const ICONS: Record<string, typeof Plug> = {
  google_drive: HardDrive,
  google_drive_api: HardDrive,
  slack: Hash,
  microsoft_365: Building2,
};

const SIGN_IN_WAIT_MS = 120_000;

function statusBadge(connector: Connector) {
  if (connector.status === "connected") return <Badge tone="success"><Check aria-hidden className="h-3 w-3" />Connected</Badge>;
  if (connector.status === "error") return <Badge tone="danger">Needs attention</Badge>;
  if (connector.auth === "oauth" && !connector.configured) return <Badge tone="warn">Needs admin setup</Badge>;
  return <Badge>Not connected</Badge>;
}

/** The Connectors dialog. */
export function ConnectorsDialog({
  onClose,
  onTry,
  onChanged,
}: {
  onClose: () => void;
  onTry: (prompt: string) => void;
  onChanged: (connectors: Connector[]) => void;
}) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const dialog = useRef<HTMLDivElement>(null);

  async function reload(): Promise<Connector[]> {
    const next = await listConnectors();
    setConnectors(next);
    onChanged(next);
    return next;
  }

  useEffect(() => {
    reload()
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ready = connectors.filter((item) => !item.custom);
  const custom = connectors.filter((item) => item.custom);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-3 sm:p-6" onClick={onClose}>
      <div
        aria-labelledby="connectors-title"
        aria-modal="true"
        className="flex max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-xl outline-none sm:max-h-[calc(100dvh-3rem)]"
        onClick={(event) => event.stopPropagation()}
        ref={dialog}
        role="dialog"
        tabIndex={-1}
      >
        <header className="flex shrink-0 items-start gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold" id="connectors-title">Connectors</h2>
            <p className="mt-0.5 text-sm text-muted">
              Let the agents pull briefs and data from your team's tools and send deliverables back. Reading runs
              straight away; anything that uploads, posts, or changes something outside Quant OS waits for your approval.
            </p>
          </div>
          <IconButton label="Close connectors" onClick={onClose}>
            <X className="h-4 w-4" />
          </IconButton>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto bg-canvas px-5 py-4">
          {error && (
            <p className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{error}</p>
          )}
          {loading && <p className="text-sm text-muted">Loading connectors…</p>}
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Ready-made</h3>
          <ul className="space-y-3">
            {ready.map((connector) => (
              <ConnectorCard connector={connector} key={connector.id} onError={setError} onReload={reload} onTry={onTry} />
            ))}
          </ul>
          <h3 className="mb-2 mt-6 text-[11px] font-semibold uppercase tracking-wider text-muted">Custom MCP servers</h3>
          <ul className="space-y-3">
            {custom.map((connector) => (
              <ConnectorCard connector={connector} key={connector.id} onError={setError} onReload={reload} onTry={onTry} />
            ))}
          </ul>
          <CustomForm onAdded={reload} onError={setError} />
        </div>
      </div>
    </div>
  );
}

function ConnectorCard({
  connector,
  onReload,
  onError,
  onTry,
}: {
  connector: Connector;
  onReload: () => Promise<Connector[]>;
  onError: (message: string) => void;
  onTry: (prompt: string) => void;
}) {
  const [busy, setBusy] = useState("");
  const [showSetup, setShowSetup] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const Icon = ICONS[connector.catalog_id] ?? Plug;
  const connected = connector.status === "connected";

  async function run(label: string, work: () => Promise<unknown>) {
    setBusy(label);
    onError("");
    try {
      await work();
      await onReload();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "The connector request failed.");
    } finally {
      setBusy("");
    }
  }

  async function signIn() {
    const started = await connectConnector(connector.id);
    if (!started.authorize_url) return;
    const popup = window.open(started.authorize_url, "quantos-connector", "width=520,height=700");
    if (!popup) throw new Error("The sign-in window was blocked. Allow pop-ups for this page and try again.");
    // Poll until the provider redirects back and the backend marks the connector connected.
    const deadline = Date.now() + SIGN_IN_WAIT_MS;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const next = await onReload();
      const current = next.find((item) => item.id === connector.id);
      if (current && current.status !== "disconnected") return;
      if (popup.closed) return;
    }
  }

  return (
    <li className="rounded-lg border border-line bg-surface p-4 shadow-xs">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Icon aria-hidden className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">{connector.name}</h4>
            <Badge>{connector.category}</Badge>
            {statusBadge(connector)}
          </div>
          <p className="mt-1 text-sm text-ink-2">{connector.description}</p>
          {connector.status_note && <p className="mt-1 text-xs text-muted">{connector.status_note}</p>}
          {connector.custom && <p className="mt-1 break-all font-mono text-xs text-muted">{connector.server_url}</p>}
          {connector.status === "error" && connector.error && (
            <p className="mt-2 rounded-md bg-danger-soft px-2.5 py-1.5 text-xs text-danger">{connector.error}</p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {connector.auth === "oauth" && !connector.configured && (
              <Button onClick={() => setShowSetup(!showSetup)} size="sm" variant="primary">
                {showSetup ? <ChevronDown aria-hidden className="h-3.5 w-3.5" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5" />}
                Setup steps
              </Button>
            )}
            {!connected && (connector.auth === "token" || connector.configured) && (
              <Button
                disabled={Boolean(busy)}
                onClick={() => void run("connect", connector.auth === "oauth" ? signIn : () => testConnector(connector.id))}
                size="sm"
                variant="primary"
              >
                <Plug aria-hidden className="h-3.5 w-3.5" />
                {busy === "connect" ? "Connecting…" : connector.status === "error" ? "Try again" : "Connect"}
              </Button>
            )}
            {connected && (
              <Button disabled={Boolean(busy)} onClick={() => void run("test", () => testConnector(connector.id))} size="sm">
                <RefreshCw aria-hidden className={clsx("h-3.5 w-3.5", busy === "test" && "animate-spin")} />
                Test
              </Button>
            )}
            {connected && connector.tools.length > 0 && (
              <Button onClick={() => setShowTools(!showTools)} size="sm" variant="ghost">
                {showTools ? <ChevronDown aria-hidden className="h-3.5 w-3.5" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5" />}
                Tools · {connector.tools.length}
              </Button>
            )}
            {!connector.custom && (
              <Button onClick={() => setShowSettings(!showSettings)} size="sm" variant="ghost">
                <Settings2 aria-hidden className="h-3.5 w-3.5" />
                Server settings
              </Button>
            )}
            {connector.configured && connector.auth === "oauth" && (
              <Button onClick={() => setShowSetup(!showSetup)} size="sm" variant="ghost">
                Setup steps
              </Button>
            )}
            {(connected || connector.custom || connector.has_token) && (
              <Button
                disabled={Boolean(busy)}
                onClick={() => void run("disconnect", () => disconnectConnector(connector.id))}
                size="sm"
                variant="ghost"
              >
                {connector.custom ? "Remove" : "Disconnect"}
              </Button>
            )}
          </div>
          {showSetup && <SetupSteps connector={connector} />}
          {showSettings && (
            <ServerSettings
              connector={connector}
              onSave={(body) => run("settings", () => updateConnector(connector.id, body)).then(() => setShowSettings(false))}
            />
          )}
          {showTools && (
            <ul className="mt-3 divide-y divide-line rounded-md border border-line">
              {connector.tools.map((tool) => (
                <li className="flex items-start gap-2 px-3 py-2" key={tool.name}>
                  <code className="shrink-0 text-xs font-semibold">{tool.name}</code>
                  <span className="min-w-0 flex-1 text-xs text-muted">{tool.description}</span>
                  <Badge tone={tool.read_only ? "neutral" : "warn"}>{tool.read_only ? "Reads" : "Needs approval"}</Badge>
                </li>
              ))}
            </ul>
          )}
          {connector.examples.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted">Try in chat:</span>
              {connector.examples.map((example) => (
                <button
                  className="rounded-full border border-line-strong px-2.5 py-0.5 text-xs text-ink-2 hover:border-accent hover:text-accent"
                  key={example}
                  onClick={() => onTry(example)}
                  type="button"
                >
                  {example}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function CopyLine({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="mt-1 flex items-center gap-1.5">
      <code className="min-w-0 flex-1 break-all rounded bg-sunken px-2 py-1 text-xs">{value}</code>
      <IconButton
        label={copied ? "Copied" : "Copy"}
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </IconButton>
    </span>
  );
}

function SetupSteps({ connector }: { connector: Connector }) {
  return (
    <div className="mt-3 rounded-md border border-line bg-sunken/50 p-3 text-sm">
      <p className="mb-2 text-xs font-semibold text-ink-2">One-time setup by an admin</p>
      <ol className="list-decimal space-y-1.5 pl-5 text-xs text-ink-2">
        {connector.setup.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {connector.redirect_uri && (
        <div className="mt-3 text-xs">
          <span className="font-medium text-ink-2">Redirect URI</span>
          <CopyLine value={connector.redirect_uri} />
        </div>
      )}
      {connector.client_env.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Settings in backend/.env: {connector.client_env.map((name) => <code className="mx-0.5" key={name}>{name}</code>)}
        </p>
      )}
      {connector.docs_url && (
        <a className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline" href={connector.docs_url} rel="noreferrer" target="_blank">
          Provider guide <ExternalLink aria-hidden className="h-3 w-3" />
        </a>
      )}
    </div>
  );
}

function ServerSettings({
  connector,
  onSave,
}: {
  connector: Connector;
  onSave: (body: { server_url?: string; scopes?: string[]; tenant_id?: string }) => Promise<unknown>;
}) {
  const [url, setUrl] = useState(connector.server_url);
  const [scopes, setScopes] = useState(connector.scopes.join(" "));
  const [tenant, setTenant] = useState("");
  const isMicrosoft = connector.catalog_id === "microsoft_365";
  return (
    <form
      className="mt-3 space-y-2 rounded-md border border-line p-3"
      onSubmit={(event) => {
        event.preventDefault();
        void onSave({
          server_url: url,
          scopes: scopes.split(/\s+/).filter(Boolean),
          ...(isMicrosoft && tenant.trim() ? { tenant_id: tenant } : {}),
        });
      }}
    >
      <Field label="MCP server URL">
        <input className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 font-mono text-xs" onChange={(event) => setUrl(event.target.value)} value={url} />
      </Field>
      <Field label="Scopes (space separated)">
        <input className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 font-mono text-xs" onChange={(event) => setScopes(event.target.value)} value={scopes} />
      </Field>
      {isMicrosoft && (
        <Field label="Tenant id (overrides MICROSOFT_TENANT_ID)">
          <input className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 font-mono text-xs" onChange={(event) => setTenant(event.target.value)} placeholder="contoso.onmicrosoft.com" value={tenant} />
        </Field>
      )}
      <p className="text-xs text-muted">Saving disconnects the connector so the next sign-in uses these settings.</p>
      <Button size="sm" type="submit" variant="primary">Save settings</Button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs font-medium text-ink-2">
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  );
}

function CustomForm({ onAdded, onError }: { onAdded: () => Promise<Connector[]>; onError: (message: string) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="mt-3 rounded-lg border border-dashed border-line-strong bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        onError("");
        addCustomConnector({ name, server_url: url, token })
          .then(async (added) => {
            await onAdded();
            if (added.status === "connected") {
              setName("");
              setUrl("");
              setToken("");
            }
          })
          .catch((reason: Error) => onError(reason.message))
          .finally(() => setBusy(false));
      }}
    >
      <p className="mb-2 text-sm font-semibold">Add a custom MCP server</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Name">
          <input className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 text-sm" onChange={(event) => setName(event.target.value)} placeholder="Client CRM" value={name} />
        </Field>
        <Field label="Server URL (streamable HTTP)">
          <input className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 font-mono text-xs" onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/mcp" required value={url} />
        </Field>
        <Field label="Access token (optional)">
          <input autoComplete="off" className="h-8 w-full rounded-md border border-line-strong bg-surface px-2 font-mono text-xs" onChange={(event) => setToken(event.target.value)} type="password" value={token} />
        </Field>
        <div className="flex items-end">
          <Button disabled={busy || !url.trim()} type="submit" variant="primary">
            <Plug aria-hidden className="h-4 w-4" />
            {busy ? "Connecting…" : "Add and connect"}
          </Button>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted">The token is encrypted on the Quant OS server and never shown again.</p>
    </form>
  );
}

function describeValue(value: unknown): string {
  if (typeof value === "string") {
    if (value.startsWith("$file:")) return "attached project file";
    if (value.startsWith("$file_text:")) return "text of a project file";
    if (value.startsWith("$file_name:")) return "project file name";
    if (value.startsWith("$file_mime:")) return "project file type";
    return value;
  }
  return JSON.stringify(value);
}

/** Cards for connector steps that wait for the researcher's approval. */
export function ConnectorApprovals({
  actions,
  onDecided,
}: {
  actions: ConnectorAction[];
  onDecided: () => Promise<void>;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const pending = actions.filter((action) => action.status === "pending");
  if (pending.length === 0) return null;

  async function decide(action: ConnectorAction, decision: "approve" | "cancel") {
    setBusy(action.id + decision);
    setError("");
    try {
      const result = await decideConnectorAction(action.id, decision);
      if (result.status === "failed") setError(result.result || "The step failed.");
      await onDecided();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The step failed.");
    } finally {
      setBusy("");
    }
  }

  return (
    <section aria-label="Steps waiting for approval" className="space-y-2">
      {pending.map((action) => (
        <article className="rounded-xl border border-warn-line bg-warn-soft/60 p-4" key={action.id}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="warn">Waiting for your approval</Badge>
            <span className="text-xs text-muted">{action.connector} · <code>{action.tool}</code></span>
          </div>
          <p className="mt-2 text-sm font-medium text-ink">{action.summary}</p>
          <dl className="mt-2 space-y-1 text-xs">
            {Object.entries(action.arguments).map(([key, value]) => {
              const text = action.display?.[key] ?? describeValue(value);
              const isFile = typeof value === "string" && value.startsWith("$file");
              return (
                <div className="flex gap-2" key={key}>
                  <dt className="w-28 shrink-0 font-mono text-muted">{key}</dt>
                  <dd className="min-w-0 flex-1 whitespace-pre-wrap break-words text-ink-2">
                    {isFile && <Paperclip aria-hidden className="mr-1 inline h-3 w-3" />}
                    {text.length > 600 ? `${text.slice(0, 600)}…` : text}
                  </dd>
                </div>
              );
            })}
          </dl>
          <div className="mt-3 flex gap-2">
            <Button disabled={Boolean(busy)} onClick={() => void decide(action, "approve")} size="sm" variant="primary">
              <Check aria-hidden className="h-3.5 w-3.5" />
              {busy === action.id + "approve" ? "Running…" : "Approve"}
            </Button>
            <Button disabled={Boolean(busy)} onClick={() => void decide(action, "cancel")} size="sm">
              Cancel
            </Button>
          </div>
        </article>
      ))}
      {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{error}</p>}
    </section>
  );
}
