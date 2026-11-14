import {
  Activity,
  ArrowUpRight,
  Code2,
  Container,
  Database,
  Download,
  DownloadCloud,
  GitBranch,
  GitCommitHorizontal,
  Globe,
  History,
  KeyRound,
  Undo2,
  Layers,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Power,
  RefreshCw,
  RotateCw,
  ScrollText,
  Settings2,
  ShieldCheck,
  Trash2,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router";
import { api, errorText } from "@/api/client";
import { keys, useCall, useCredentials, useHistory, useInstance, useJobs, useOdooLog } from "@/api/queries";
import type { Instance, InstanceBackup, Job, Permission } from "@/api/types";
import { BACKUP_KIND as KIND_LABEL, BackupPicker } from "@/components/BackupPicker";
import { LiveChart } from "@/components/charts/LiveChart";
import { JobLine, Monogram } from "@/components/InstanceCard";
import { JobDrawer, Terminal } from "@/components/JobDrawer";
import { Page, useCan } from "@/components/Shell";
import { StatCard } from "@/components/StatCard";
import { Button, Callout, CopyField, Empty, Field, Progress, Segmented, Skeleton, Status, Switch, Tag } from "@/components/ui/basics";
import { Menu, Modal, useToast } from "@/components/ui/overlay";
import { ago, bytes, dateTime, duration, elapsed, ms, percent } from "@/lib/format";
import { NotFoundPage } from "./NotFound";

type Action = { action: string; body?: Record<string, unknown>; title: string };

function useRun(name: string, openJob: (id: string) => void) {
  const toast = useToast();
  return useCall(
    async ({ action, body, title }: Action) => {
      try {
        const job = await api.post<Job>(`/instances/${name}/actions/${action}`, body ?? {});
        toast("success", `${title} started`, "Follow it in Activity.");
        openJob(job.id);
        return job;
      } catch (error) {
        toast("error", `${title} did not start`, errorText(error));
        throw error;
      }
    },
    [keys.instance(name), keys.jobs(name)],
  );
}

const TABS: { id: string; label: string; icon: React.ReactNode; permission?: Permission }[] = [
  { id: "", label: "Overview", icon: <Activity /> },
  { id: "activity", label: "Activity", icon: <Layers /> },
  { id: "code", label: "Code", icon: <Code2 /> },
  { id: "logs", label: "Odoo log", icon: <ScrollText />, permission: "instances.logs" },
  { id: "settings", label: "Settings", icon: <Settings2 />, permission: "instances.operate" },
  { id: "access", label: "Access", icon: <KeyRound />, permission: "instances.credentials" },
];

export function InstancePage() {
  const { name = "", tab = "" } = useParams();
  const can = useCan();
  const { data: instance, isPending, error } = useInstance(name);
  const [jobId, setJobId] = useState<string | null>(null);
  const run = useRun(name, setJobId);
  const [dialog, setDialog] = useState<null | "upgrade" | "branch" | "delete" | "submodule" | "rollback">(null);

  if (error && !instance) return <NotFoundPage />;
  if (isPending || !instance)
    return (
      <Page>
        <Skeleton height={64} width="50%" />
        <Skeleton height={300} />
      </Page>
    );

  const busy = !!instance.current_job;
  const asleep = ["paused", "switched_off", "stopped"].includes(instance.status);
  const act = (action: string, title: string, body?: Record<string, unknown>) => run.mutate({ action, title, body });

  return (
    <Page>
      <div className="page-head">
        <div className="hero spacer">
          <Monogram name={instance.name} large />
          <div className="titles" style={{ minWidth: 0 }}>
            <div className="row-wrap" style={{ gap: 12 }}>
              <h1 className="truncate">{instance.name}</h1>
              <Status status={instance.status} />
            </div>
            <div className="row-wrap small muted">
              <Tag mono>{instance.odoo.version}</Tag>
              <Tag>{instance.odoo.edition === "enterprise" ? "Enterprise" : "Community"}</Tag>
              <span className="row mono xsmall" style={{ gap: 4 }}>
                <GitBranch size={14} strokeWidth={1.5} /> {instance.git.branch}
              </span>
              {instance.url && (
                <a href={instance.url} target="_blank" rel="noreferrer" className="row truncate mono xsmall" style={{ gap: 4 }}>
                  <Globe size={14} strokeWidth={1.5} /> {instance.url.replace(/^https?:\/\//, "")}
                </a>
              )}
            </div>
          </div>
        </div>
        <div className="actions">
          {instance.url && !asleep && (
            <a className="btn primary" href={instance.url} target="_blank" rel="noreferrer">
              Open Odoo <ArrowUpRight />
            </a>
          )}
          {can("instances.update") &&
            (asleep ? (
              <Button variant="primary" icon={<Play />} disabled={busy} onClick={() => act("start", "Start")}>
                Start
              </Button>
            ) : (
              <Button icon={<RotateCw />} disabled={busy} onClick={() => act("restart", "Restart")}>
                Restart
              </Button>
            ))}
          {can("instances.update") && (
            <Button icon={<DownloadCloud />} disabled={busy || !instance.git.repository} onClick={() => act("update", "Get latest code")}>
              Get latest code
            </Button>
          )}
          {(can("instances.update") || can("instances.operate")) && (
          <Menu trigger={(toggle) => <Button icon={<MoreHorizontal />} onClick={toggle} aria-label="More actions" />}>
            {(close) => {
              const item = (fn: () => void) => () => {
                close();
                fn();
              };
              return (
                <>
                  <button disabled={busy || !instance.git.repository} onClick={item(() => act("update-submodules", "Update submodules"))}>
                    <RefreshCw /> Update submodules
                  </button>
                  {can("instances.operate") && (
                    <>
                      <button disabled={busy} onClick={item(() => setDialog("upgrade"))}>
                        <Zap /> Upgrade modules…
                      </button>
                      <button disabled={busy || !instance.git.repository} onClick={item(() => setDialog("branch"))}>
                        <GitBranch /> Switch branch…
                      </button>
                      <button disabled={busy} onClick={item(() => act("update-images", "Update Odoo and PostgreSQL images"))}>
                        <Container /> Update Odoo and PostgreSQL images
                      </button>
                      <hr />
                      {!asleep && (
                        <button disabled={busy} onClick={item(() => act("pause", "Pause"))}>
                          <Pause /> Pause
                        </button>
                      )}
                      {instance.status !== "switched_off" && (
                        <button disabled={busy} onClick={item(() => act("switch-off", "Switch off"))}>
                          <Power /> Switch off
                        </button>
                      )}
                    </>
                  )}
                  {can("instances.delete") && (
                    <button className="danger" disabled={busy} onClick={item(() => setDialog("delete"))}>
                      <Trash2 /> Delete…
                    </button>
                  )}
                </>
              );
            }}
          </Menu>
          )}
        </div>
      </div>

      {instance.current_job && (
        <button className="card pad" style={{ textAlign: "left", cursor: "pointer" }} onClick={() => setJobId(instance.current_job!.id)}>
          <JobLine job={{ ...instance.current_job, steps: [] }} />
        </button>
      )}
      {instance.rollback && can("instances.restore") && (
        <div className="rollback-banner" role="status">
          <Undo2 />
          <div className="text small">
            <b>Restored {ago(instance.rollback.taken_at)}.</b> The state before the restore is kept until {dateTime(instance.rollback.until)}; you can go back to it until then.
          </div>
          <Button variant="primary" icon={<Undo2 />} disabled={busy} onClick={() => setDialog("rollback")}>
            Rollback to before the restore
          </Button>
        </div>
      )}
      {instance.git.branch_deleted_on_github && (
        <Callout tone="warning">
          The branch <b>{instance.git.branch}</b> no longer exists on GitHub, so this instance gets no updates. Switch it to another branch, or delete it.
        </Callout>
      )}
      {instance.gateway_error && <Callout tone="danger">{instance.gateway_error}</Callout>}
      {instance.drift && (
        <Callout tone="danger">
          <b>Changed outside the panel {instance.drift.detected_at ? ago(instance.drift.detected_at) : ""}.</b>{" "}
          {instance.drift.action === "restore"
            ? "The panel puts its own configuration back as soon as nothing else runs here, backing the database up first when its container is affected."
            : "The panel only reports this. Undo the change, or restore the panel's configuration."}
          <ul className="drift-list mono xsmall">
            {instance.drift.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          {instance.drift.action === "warn" && can("instances.operate") && (
            <Button icon={<ShieldCheck />} disabled={busy} onClick={() => act("repair", "Restore the panel's configuration")}>
              Restore the panel's configuration
            </Button>
          )}
        </Callout>
      )}

      <nav className="tabs">
        {TABS.filter((t) => !t.permission || can(t.permission)).map((t) => (
          <NavLink key={t.id} to={`/i/${name}${t.id ? `/${t.id}` : ""}`} end viewTransition className={({ isActive }) => (isActive ? "active" : "")}>
            {t.icon} {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="rise" key={tab}>
        {tab === "" && <Overview instance={instance} busy={busy} act={act} />}
        {tab === "activity" && <ActivityTab name={name} onOpen={setJobId} />}
        {tab === "code" && <CodeTab instance={instance} canAdd={can("instances.update")} canRemove={can("instances.operate")} busy={busy} onAdd={() => setDialog("submodule")} act={act} />}
        {tab === "logs" && can("instances.logs") && <LogsTab name={name} />}
        {tab === "settings" && can("instances.operate") && <SettingsTab instance={instance} />}
        {tab === "access" && can("instances.credentials") && <AccessTab instance={instance} />}
      </div>

      {jobId && <JobDrawer id={jobId} onClose={() => setJobId(null)} />}
      {dialog === "upgrade" && <UpgradeDialog onClose={() => setDialog(null)} onRun={(modules) => act("upgrade", "Upgrade modules", { modules })} />}
      {dialog === "branch" && <BranchDialog instance={instance} onClose={() => setDialog(null)} onRun={(branch) => act("switch-branch", "Switch branch", { branch })} />}
      {dialog === "submodule" && <SubmoduleDialog version={instance.odoo.version} onClose={() => setDialog(null)} onRun={(body) => act("add-submodule", "Add submodule", body)} />}
      {dialog === "delete" && <DeleteDialog name={name} onClose={() => setDialog(null)} />}
      {dialog === "rollback" && instance.rollback && (
        <RollbackDialog instance={instance} onClose={() => setDialog(null)} onRun={() => act("rollback", "Rollback")} />
      )}
    </Page>
  );
}

// ---------------------------------------------------------------- overview

const METRICS = {
  cpu_percent: { label: "Processor", format: (v: number) => `${v.toFixed(1)}%` },
  memory_percent: { label: "Memory", format: (v: number) => `${Math.round(v)}%`, max: 100 },
  requests_per_minute: { label: "Requests per minute", format: (v: number) => v.toFixed(0) },
  response_ms_p95: { label: "Response time, 95th percentile", format: (v: number) => `${Math.round(v)} ms` },
} as const;
type Metric = keyof typeof METRICS;

function Overview({ instance, busy, act }: { instance: Instance; busy: boolean; act: (action: string, title: string, body?: Record<string, unknown>) => void }) {
  const { data: history } = useHistory();
  const [metric, setMetric] = useState<Metric>("cpu_percent");
  const series = history?.instances[instance.name];
  const u = instance.usage;
  const chosen = METRICS[metric];
  return (
    <div className="stack">
      <div className="grid-4 stagger">
        <StatCard label="Processor" value={u.cpu_percent ?? null} unit="%" decimals={1} detail="of the whole server"
          trend={{ t: series?.t ?? [], values: series?.cpu_percent ?? [] }} />
        <StatCard label="Memory" value={u.memory_percent != null ? Math.round(u.memory_percent) : null} unit="%"
          detail={`${bytes(u.memory_bytes)} of ${bytes(u.memory_limit_bytes)}`}
          trend={{ t: series?.t ?? [], values: series?.memory_percent ?? [], max: 100 }} />
        <StatCard label="Requests" value={u.requests_per_minute != null ? Math.round(u.requests_per_minute) : null} unit="/min"
          detail={u.error_rate_percent ? `${percent(u.error_rate_percent, 1)} answered with an error` : "no errors"}
          trend={{ t: series?.t ?? [], values: series?.requests_per_minute ?? [] }} />
        <StatCard label="Response time" value={u.response_ms_p95 != null ? Math.round(u.response_ms_p95) : null} unit="ms"
          detail={`95% of requests faster · average ${ms(u.response_ms_avg)}`}
          trend={{ t: series?.t ?? [], values: series?.response_ms_p95 ?? [] }} />
      </div>

      <div className="overview">
        <section className="card chart-card">
          <div className="chart-head">
            <h2>{chosen.label}</h2>
            <span className="spacer" />
            <Segmented<Metric>
              value={metric}
              onChange={setMetric}
              options={[
                { value: "cpu_percent", label: "CPU" },
                { value: "memory_percent", label: "Memory" },
                { value: "requests_per_minute", label: "Requests" },
                { value: "response_ms_p95", label: "Response" },
              ]}
            />
          </div>
          <div className="chart-body">
            <LiveChart
              t={series?.t ?? []}
              max={"max" in chosen ? chosen.max : undefined}
              format={chosen.format}
              series={[{ label: chosen.label, values: series?.[metric] ?? [], color: "--accent", fill: true }]}
            />
          </div>
        </section>
        <section className="card">
          <div className="card-head"><h2>Details</h2></div>
          <div className="card-body">
            <dl className="dl small">
              <dt>Database</dt>
              <dd className="mono">{instance.odoo.database}</dd>
              <dt>Repository</dt>
              <dd className="truncate">{instance.git.repository ? <a href={instance.git.repository} target="_blank" rel="noreferrer">{instance.git.repository.replace(/^https:\/\/github\.com\//, "")}</a> : <span className="faint">None</span>}</dd>
              <dt>Running for</dt>
              <dd>{duration(u.uptime_seconds)}</dd>
              <dt>Disk</dt>
              <dd>{instance.disk ? `${bytes(instance.disk.database_bytes)} database, ${bytes(instance.disk.files_bytes)} files` : bytes(u.disk_bytes)}</dd>
              <dt>Last visit</dt>
              <dd>{ago(instance.last_visit_at)}</dd>
              <dt>Pauses</dt>
              <dd>{instance.pauses_at ? `${ago(instance.pauses_at)} if nobody visits` : instance.settings.auto_pause ? "When idle" : "Never"}</dd>
              <dt>Created</dt>
              <dd>{dateTime(instance.created_at)}{instance.created_by ? ` by ${instance.created_by}` : ""}</dd>
              <dt>Deleted</dt>
              <dd>{instance.expires_at ? `${dateTime(instance.expires_at)}, after a backup` : "Kept until deleted by hand"}</dd>
            </dl>
          </div>
        </section>
      </div>
      <BackupsCard instance={instance} busy={busy} act={act} />
    </div>
  );
}

// ---------------------------------------------------------------- backups

function BackupsCard({ instance, busy, act }: { instance: Instance; busy: boolean; act: (action: string, title: string, body?: Record<string, unknown>) => void }) {
  const can = useCan();
  const [restoring, setRestoring] = useState<InstanceBackup | null>(null);
  const [picking, setPicking] = useState(false);
  const list = instance.backups ?? [];
  const latest = list.find((b) => b.file === instance.restorable_backup);
  return (
    <section className="card">
      <div className="card-head">
        <h2>Backups</h2>
        <span className="sub">{list.length ? `${list.length} kept` : "None yet"}</span>
        <span className="spacer" />
        {can("instances.operate") && (
          <Button size="sm" icon={<Database />} disabled={busy} onClick={() => act("backup", "Back up")}>Back up now</Button>
        )}
        {can("instances.restore") && (
          <Button size="sm" icon={<History />} disabled={busy || !latest} onClick={() => latest && setRestoring(latest)}>
            Restore the latest
          </Button>
        )}
        {can("instances.restore") && can("backups.manage") && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPicking(true)}>
            Restore another backup…
          </Button>
        )}
      </div>
      {latest ? (
        <div className="backup-latest">
          <div>
            <div className="small muted">Latest backup</div>
            <div className="when">{dateTime(latest.created_at)}</div>
            <div className="xsmall faint">{KIND_LABEL[latest.kind]} · {bytes(latest.size_bytes)} · {ago(latest.created_at)}</div>
          </div>
        </div>
      ) : (
        <p className="card-body small muted">
          A daily backup is taken each night after a day the instance was used. Back up now to have one right away.
        </p>
      )}
      {list.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Taken</th><th>Kind</th><th>Size</th><th /></tr></thead>
            <tbody>
              {list.map((b) => (
                <tr key={b.file}>
                  <td>{dateTime(b.created_at)} <span className="faint xsmall">· {ago(b.created_at)}</span></td>
                  <td><Tag tone={b.kind === "daily" ? "accent" : undefined}>{KIND_LABEL[b.kind]}</Tag></td>
                  <td className="mono small">{bytes(b.size_bytes)}</td>
                  <td className="actions">
                    {can("backups.manage") && (
                      <a className="btn sm ghost" href={`/api/v1/backups/${b.file}`} download aria-label={`Download ${b.file}`}><Download /></a>
                    )}
                    {can("instances.restore") && (
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => setRestoring(b)}>Restore</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {restoring && (
        <RestoreDialog instance={instance} backup={restoring} onClose={() => setRestoring(null)}
          onRun={() => act("restore", "Restore", { file: restoring.file })} />
      )}
      {picking && (
        <AnotherBackupDialog instance={instance} onClose={() => setPicking(false)}
          onRun={(file) => act("restore", "Restore", { file })} />
      )}
    </section>
  );
}

function RestoreDialog({ instance, backup, onClose, onRun }: { instance: Instance; backup: InstanceBackup; onClose: () => void; onRun: () => void }) {
  return (
    <Modal title={`Restore the backup of ${dateTime(backup.created_at)}?`} description={`${KIND_LABEL[backup.kind]} · ${bytes(backup.size_bytes)}`} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" onClick={() => { onRun(); onClose(); }}>Restore</Button></>}>
      <div className="stack">
        <Callout tone="warning">
          The database <b className="mono">{backup.database}</b> and its files go back to how they were on {dateTime(backup.created_at)}. Changes made since then are replaced.
        </Callout>
        <p className="small muted">
          The current state is backed up first and kept as "Before a restore": the instance offers <b>Rollback</b> for a while afterwards. {instance.name} restarts and is back in a minute or two.
        </p>
      </div>
    </Modal>
  );
}

function AnotherBackupDialog({ instance, onClose, onRun }: { instance: Instance; onClose: () => void; onRun: (file: string) => void }) {
  const [file, setFile] = useState<string | null>(null);
  const foreign = !!file && !file.startsWith(`${instance.name}__`);
  return (
    <Modal wide title="Restore another backup" description={`Any backup of Odoo ${instance.odoo.version} can go into ${instance.name}, also one of another instance.`} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" disabled={!file} onClick={() => { if (file) { onRun(file); onClose(); } }}>Restore</Button></>}>
      <div className="stack">
        <BackupPicker version={instance.odoo.version} edition={instance.odoo.edition} value={file} onChange={setFile} />
        {file && (
          <Callout tone="warning">
            The database <b className="mono">{instance.odoo.database}</b> and its files are replaced by the backup's. The current state is backed up first and offered as <b>Rollback</b> for a while.
            {foreign && <> The data comes from another instance, so it is neutralised: it sends no e-mail and runs no scheduled actions until you switch them back on in Odoo.</>}
          </Callout>
        )}
      </div>
    </Modal>
  );
}

function RollbackDialog({ instance, onClose, onRun }: { instance: Instance; onClose: () => void; onRun: () => void }) {
  const rollback = instance.rollback!;
  return (
    <Modal title="Rollback to before the restore?" description={`To the state of ${dateTime(rollback.taken_at)}`} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" icon={<Undo2 />} onClick={() => { onRun(); onClose(); }}>Rollback</Button></>}>
      <div className="stack">
        <Callout tone="warning">
          The database and its files go back to how they were just before the restore of {dateTime(rollback.taken_at)}. Changes made since the restore are replaced.
        </Callout>
        <p className="small muted">
          The current state is backed up first and kept as "Before a rollback" until {dateTime(rollback.until)}. {instance.name} restarts and is back in a minute or two.
        </p>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- activity

function JobRow({ job, onOpen }: { job: Job; onOpen: (id: string) => void }) {
  return (
    <button className="job-row" onClick={() => onOpen(job.id)}>
      <Status status={job.status} />
      <div style={{ minWidth: 0 }}>
        <div className="truncate">{job.action}</div>
        <div className="xsmall faint">
          {job.instance} · {job.requested_by} · {ago(job.started_at)}
          {job.finished_at && ` · took ${elapsed(job.started_at, job.finished_at)}`}
        </div>
        {job.error && <div className="xsmall" style={{ color: "var(--negative)" }}>{job.error}</div>}
      </div>
      <Progress value={job.progress_percent} status={job.status} />
    </button>
  );
}

export function JobList({ jobs, onOpen }: { jobs: Job[] | undefined; onOpen: (id: string) => void }) {
  if (!jobs) return <div className="card-body"><Skeleton height={120} /></div>;
  if (!jobs.length) return <Empty icon={<Layers />} title="No activity yet">Actions on this instance appear here, with their progress.</Empty>;
  return <>{jobs.map((job) => <JobRow key={job.id} job={job} onOpen={onOpen} />)}</>;
}

function ActivityTab({ name, onOpen }: { name: string; onOpen: (id: string) => void }) {
  const { data: jobs } = useJobs(name);
  return (
    <div className="card">
      <JobList jobs={jobs} onOpen={onOpen} />
    </div>
  );
}

// ---------------------------------------------------------------- code

function CodeTab({ instance, canAdd, canRemove, busy, onAdd, act }: { instance: Instance; canAdd: boolean; canRemove: boolean; busy: boolean; onAdd: () => void; act: (action: string, title: string, body?: Record<string, unknown>) => void }) {
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <div className="card">
        <div className="card-head">
          <h2>Recent commits</h2>
          <span className="sub">{instance.git.branch}</span>
        </div>
        {instance.recent_commits?.length ? (
          <ol className="timeline card-body">
            {instance.recent_commits.map((c, i) => (
              <li key={c.sha}>
                <span className={`node ${i === 0 ? "done" : ""}`}><GitCommitHorizontal /></span>
                <div style={{ minWidth: 0 }}>
                  <div className="truncate">{c.subject}</div>
                  <div className="xsmall faint"><span className="mono">{c.sha}</span> · {c.author} · {c.when}</div>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <Empty icon={<GitCommitHorizontal />} title="No commits">This instance has no code from GitHub.</Empty>
        )}
      </div>
      <div className="card">
        <div className="card-head">
          <h2>Submodules</h2>
          <span className="spacer" />
          {canAdd && <Button size="sm" icon={<Plus />} disabled={busy || !instance.git.repository} onClick={onAdd}>Add</Button>}
        </div>
        {instance.submodules?.length ? (
          <table className="table">
            <tbody>
              {instance.submodules.map((s) => (
                <tr key={s.path}>
                  <td>
                    <div>{s.path}</div>
                    <div className="xsmall faint truncate">{s.url}</div>
                  </td>
                  <td className="mono xsmall">{s.sha}</td>
                  <td className="actions">
                    {canRemove && (
                      <Button size="sm" variant="ghost" icon={<Trash2 />} disabled={busy} aria-label="Remove" onClick={() => confirm(`Remove submodule ${s.path}? The change is pushed to GitHub.`) && act("remove-submodule", "Remove submodule", { path: s.path })} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty icon={<Layers />} title="No submodules">Add other repositories (OCA modules, shared add-ons) to this branch.</Empty>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- logs

function LogsTab({ name }: { name: string }) {
  const [lines, setLines] = useState(300);
  const { data, isFetching, refetch } = useOdooLog(name, lines);
  return (
    <div className="stack">
      <div className="row">
        <select className="select" style={{ width: 180 }} value={lines} onChange={(e) => setLines(Number(e.target.value))}>
          {[100, 300, 1000, 3000].map((n) => <option key={n} value={n}>Last {n} lines</option>)}
        </select>
        <Button icon={<RefreshCw />} loading={isFetching} onClick={() => refetch()}>Refresh</Button>
      </div>
      {data ? <Terminal text={data.text || "No log output yet."} /> : <Skeleton height={300} />}
    </div>
  );
}

// ---------------------------------------------------------------- settings

function SettingsTab({ instance }: { instance: Instance }) {
  const toast = useToast();
  const save = useCall((body: Record<string, unknown>) => api.patch<Instance>(`/instances/${instance.name}`, body), [keys.instance(instance.name), keys.instances]);
  const set = (body: Record<string, unknown>) =>
    save.mutate(body, { onSuccess: () => toast("success", "Saved"), onError: (e) => toast("error", "Not saved", errorText(e)) });
  const s = instance.settings;
  const rows: [keyof typeof s, string, string][] = [
    ["auto_update", "Get new code automatically", "When the branch on GitHub has new commits, update this instance."],
    ["auto_upgrade", "Upgrade changed modules", "After an update, upgrade the modules whose code changed."],
    ["auto_pause", "Pause when idle", "Free the server's memory when nobody has opened it for a while; the next visit starts it again."],
  ];
  return (
    <div className="card">
      {rows.map(([key, title, text]) => (
        <div className="settings-row" key={key}>
          <div><div className="name">{title}</div><div className="desc">{text}</div></div>
          <div style={{ justifySelf: "end" }}><Switch checked={s[key] as boolean} onChange={(v) => set({ [key]: v })} /></div>
        </div>
      ))}
      <div className="settings-row">
        <div><div className="name">Lifetime</div><div className="desc">Deleted automatically this many days after it was created, after a backup.</div></div>
        <select className="select" value={s.delete_after_days} onChange={(e) => set({ delete_after_days: Number(e.target.value) })}>
          {[...new Set([7, 14, 30, 60, 90, 180, s.delete_after_days])].filter((d) => d > 0).sort((a, b) => a - b).map((d) => <option key={d} value={d}>{d} days</option>)}
          <option value={0}>Keep until deleted by hand</option>
        </select>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- access

function AccessTab({ instance }: { instance: Instance }) {
  const [shown, setShown] = useState(false);
  const { data, isFetching } = useCredentials(instance.name, shown);
  return (
    <div className="card">
      <div className="card-head"><h2>Odoo sign-in</h2><span className="spacer" /><span className="sub">viewing is recorded in the audit log</span></div>
      <div className="card-body">
        {!shown ? (
          <Button icon={<KeyRound />} onClick={() => setShown(true)}>Show the passwords</Button>
        ) : !data ? (
          isFetching && <Skeleton height={100} />
        ) : (
          <dl className="dl">
            <dt>Address</dt><dd>{instance.url ? <CopyField value={instance.url} /> : "—"}</dd>
            <dt>Login</dt><dd><CopyField value={data.login} /></dd>
            <dt>Password</dt><dd><CopyField value={data.admin_password} secret /></dd>
            <dt>Master password</dt><dd><CopyField value={data.master_password} secret /> <span className="xsmall faint">for the database manager</span></dd>
            <dt>Ports</dt><dd className="mono small">{Object.entries(data.ports).map(([k, v]) => `${k} ${v}`).join(" · ")}</dd>
          </dl>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- dialogs

function UpgradeDialog({ onClose, onRun }: { onClose: () => void; onRun: (modules: string) => void }) {
  const [modules, setModules] = useState("");
  return (
    <Modal title="Upgrade modules" description="Runs Odoo's upgrade for these modules, then restarts the instance." onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!modules.trim()} onClick={() => { onRun(modules.trim()); onClose(); }}>Upgrade</Button></>}>
      <Field label="Modules" hint={<>Technical names separated by commas, or <code>all</code>.</>}>
        <input className="input mono" autoFocus placeholder="sale_custom,stock_custom" value={modules} onChange={(e) => setModules(e.target.value)} />
      </Field>
    </Modal>
  );
}

function BranchDialog({ instance, onClose, onRun }: { instance: Instance; onClose: () => void; onRun: (branch: string) => void }) {
  const [branch, setBranch] = useState("");
  const [branches, setBranches] = useState<string[] | null>(null);
  const [error, setError] = useState("");
  if (branches === null && !error && instance.git.repository)
    api.get<{ branches: string[] }>(`/repositories/branches?url=${encodeURIComponent(instance.git.repository)}`).then((r) => setBranches(r.branches), (e) => setError(errorText(e)));
  return (
    <Modal title="Switch branch" description="The instance restarts with the code of the other branch, and upgrades its modules." onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!branch} onClick={() => { onRun(branch); onClose(); }}>Switch</Button></>}>
      {error ? <Callout tone="danger">{error}</Callout> : (
        <Field label="Branch">
          <select className="select" value={branch} onChange={(e) => setBranch(e.target.value)} disabled={!branches}>
            <option value="">{branches ? "Choose a branch" : "Loading branches…"}</option>
            {branches?.filter((b) => b !== instance.git.branch).map((b) => <option key={b}>{b}</option>)}
          </select>
        </Field>
      )}
    </Modal>
  );
}

function SubmoduleDialog({ version, onClose, onRun }: { version: string; onClose: () => void; onRun: (body: Record<string, unknown>) => void }) {
  const [url, setUrl] = useState("");
  const [path, setPath] = useState("");
  const [branch, setBranch] = useState(version);
  return (
    <Modal title="Add a submodule" description="Adds the repository to this branch and pushes the change to GitHub." onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!url} onClick={() => { onRun({ url, path, branch }); onClose(); }}>Add</Button></>}>
      <div className="stack">
        <Field label="Repository"><input className="input" autoFocus placeholder="https://github.com/OCA/web" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <div className="grid-2">
          <Field label="Folder" hint="Empty: the repository's name"><input className="input" placeholder="oca/web" value={path} onChange={(e) => setPath(e.target.value)} /></Field>
          <Field label="Branch"><input className="input" value={branch} onChange={(e) => setBranch(e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  );
}

function DeleteDialog({ name, onClose }: { name: string; onClose: () => void }) {
  const [typed, setTyped] = useState("");
  const navigate = useNavigate();
  const toast = useToast();
  const remove = useCall(() => api.del<Job>(`/instances/${name}`, { confirm: name }), [keys.jobs()]);
  return (
    <Modal title={`Delete ${name}?`} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" icon={<Trash2 />} loading={remove.isPending} disabled={typed !== name}
        onClick={() => remove.mutate(undefined, { onSuccess: () => { toast("success", "Deletion started", "A backup is taken first"); navigate("/", { viewTransition: true }); }, onError: (e) => toast("error", "Not deleted", errorText(e)) })}>Delete</Button></>}>
      <div className="stack">
        <Callout tone="danger"><b>Odoo, its database and its files are removed.</b> A backup is taken first and kept under Backups.</Callout>
        <Field label={<>Type <code>{name}</code> to confirm</>}>
          <input className="input" autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
