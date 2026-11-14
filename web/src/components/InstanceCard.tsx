import { ArrowUpRight, GitBranch } from "lucide-react";
import { Link } from "react-router";
import { useJob } from "@/api/queries";
import type { Instance, Job } from "@/api/types";
import { ago, monogram, percent } from "@/lib/format";
import { Progress, Status, Tag } from "./ui/basics";

export function Monogram({ name, large }: { name: string; large?: boolean }) {
  return <span className={`monogram ${large ? "lg" : ""}`}>{monogram(name).letters}</span>;
}

function RunningJob({ id }: { id: string }) {
  const { data: job } = useJob(id);
  return job ? <JobLine job={job} /> : null;
}

export function JobLine({ job }: { job: Pick<Job, "action" | "status" | "progress_percent" | "steps"> }) {
  const step = job.steps?.findLast?.((s) => s.status === "running")?.title;
  return (
    <div className="stack-sm">
      <div className="row small">
        <span className="truncate">{job.action}</span>
        <span className="spacer" />
        <span className="mono faint xsmall">{job.progress_percent != null ? `${job.progress_percent}%` : ""}</span>
      </div>
      <Progress value={job.progress_percent} status={job.status} />
      {step && <span className="xsmall faint truncate">{step}</span>}
    </div>
  );
}

export function InstanceCard({ instance }: { instance: Instance }) {
  const usage = instance.usage;
  return (
    <article className="card link instance-card">
      <div className="ic-head">
        <Monogram name={instance.name} />
        <div style={{ minWidth: 0, flex: 1 }}>
          {/* the whole card opens the instance: this link covers it (.ic-open::after), the Open button sits above */}
          <Link to={`/i/${instance.name}`} viewTransition className="ic-name ic-open truncate">{instance.name}</Link>
          <div className="ic-sub">
            <GitBranch />
            <span className="truncate">{instance.git.branch}</span>
          </div>
        </div>
        <Status status={instance.status} />
      </div>
      <div className="ic-body">
        <div className="row-wrap">
          <Tag mono>{instance.odoo.version}</Tag>
          <Tag>{instance.odoo.edition === "enterprise" ? "Enterprise" : "Community"}</Tag>
          {instance.git.branch_deleted_on_github && <Tag tone="negative">Branch deleted</Tag>}
          {instance.drift && <Tag tone="negative">Changed outside the panel</Tag>}
        </div>
        {instance.current_job ? (
          <RunningJob id={instance.current_job.id} />
        ) : instance.git.commit ? (
          <div className="ic-commit">
            <span className="sha">{instance.git.commit.sha}</span>
            <span className="truncate">{instance.git.commit.subject}</span>
          </div>
        ) : (
          <div className="ic-commit faint">No code from GitHub</div>
        )}
        <div className="ic-stats">
          <div>
            <span className="k">CPU</span>
            <span className="v">{percent(usage.cpu_percent, 1)}</span>
          </div>
          <div>
            <span className="k">Memory</span>
            <span className="v">{percent(usage.memory_percent)}</span>
          </div>
          <div>
            <span className="k">Requests/min</span>
            <span className="v">{usage.requests_per_minute != null ? Math.round(usage.requests_per_minute) : "—"}</span>
          </div>
        </div>
      </div>
      <div className="ic-foot">
        <span className="truncate">
          {instance.last_visit_at ? `Visited ${ago(instance.last_visit_at)}` : `Created ${ago(instance.created_at)}`}
        </span>
        <span className="spacer" />
        {instance.url && instance.status !== "switched_off" && (
          <a className="btn sm ghost ic-external" href={instance.url} target="_blank" rel="noreferrer">
            Open <ArrowUpRight />
          </a>
        )}
      </div>
    </article>
  );
}
