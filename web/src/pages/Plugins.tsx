// Plugins: the marketplace's catalogue, the installed plugins (versions, updates, licences) and the purchases of
// this server. Installing is one click for a free plugin: a job downloads and verifies the package, then the backend
// restarts on its own and a toast says when the plugin is ready. Buying opens a checkout session: the account owner
// pays on app.sudoo.sh in another tab, this page follows it and installs once paid. The panel never charges anything
// and never shows a plugin's code.

import { useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, FileDown, MapPin, Puzzle, Receipt, Search, ShoppingBag, Sparkles, Star, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router";
import { api, ApiError, errorText } from "@/api/client";
import {
  keys,
  useBilling,
  useCatalog,
  useCatalogPlugin,
  useCategories,
  useJob,
  useMarketplace,
  usePlugins,
  usePurchases,
  useReceipts,
  useRecommendations,
} from "@/api/queries";
import type { CatalogPlugin, CheckoutSession, InstalledPlugin, Job, PricePlan, Recommendation } from "@/api/types";
import { JobLine, Monogram } from "@/components/InstanceCard";
import { JobDrawer } from "@/components/JobDrawer";
import { LinkForm, marketplaceProblem, PublisherBadge } from "@/components/Marketplace";
import { Page, PageHead, useCan } from "@/components/Shell";
import { Button, Callout, Empty, Field, Segmented, Skeleton, Status, Tag } from "@/components/ui/basics";
import { Menu, Modal, useToast } from "@/components/ui/overlay";
import { ago, day, money, number } from "@/lib/format";
import { waitForBackend } from "@/lib/restart";

const TYPE_LABEL: Record<string, string> = {
  auth: "Sign-in",
  second_factor: "Second factor",
  mailer: "E-mail",
  exposure: "Exposure",
  update_trigger: "Code updates",
  addon_source: "Add-on source",
  storage: "Storage",
  rate_limiter: "Rate limits",
  backup: "Backups",
  notification: "Notifications",
  instance_hook: "Instance hooks",
  dashboard_widget: "Dashboard",
  web_page: "Pages",
  background_task: "Background work",
  theme: "Themes",
  api: "API",
  mcp: "MCP",
  extension: "Extensions",
};
const PLAN_NAME: Record<string, string> = { monthly: "Monthly", yearly: "Yearly", fixed_term: "Fixed term", one_time: "One time" };

/** An amount without ".00" when it is whole: 10000, "usd" -> "$100". */
function price(cents: number, currency: string) {
  const text = money(cents, currency);
  return cents % 100 === 0 ? text.replace(/[.,]00(?=\D*$)/, "") : text;
}

/** "$100/year · $8.33/month · save 17%", "$250 once, no renewal", "$30 for 90 days · $10.15/month". */
export function planPrice(plan: PricePlan) {
  const parts: string[] = [];
  if (plan.kind === "one_time" || plan.perpetual) return `${price(plan.price_cents, plan.currency)} once, no renewal`;
  if (plan.kind === "fixed_term") parts.push(`${price(plan.price_cents, plan.currency)} for ${plan.period_days ?? "?"} days`);
  else parts.push(`${price(plan.price_cents, plan.currency)}/${plan.kind === "yearly" ? "year" : "month"}`);
  if (plan.kind !== "monthly" && plan.monthly_equivalent_cents != null) parts.push(`${money(plan.monthly_equivalent_cents, plan.currency)}/month`);
  if (plan.savings_percent) parts.push(`save ${plan.savings_percent}%`);
  return parts.join(" · ");
}

/** Free, or the cheapest plan (the hub lists plans cheapest first). */
function priceOf(plugin: Pick<CatalogPlugin, "tier"> & { plans?: PricePlan[] }) {
  if (plugin.tier === "free") return "Free";
  const plan = plugin.plans?.[0];
  if (!plan) return "Paid";
  return plan.perpetual ? `${price(plan.price_cents, plan.currency)} once` : `${price(plan.price_cents, plan.currency)}/${plan.kind === "yearly" ? "year" : plan.kind === "fixed_term" ? `${plan.period_days ?? "?"} days` : "month"}`;
}

/** The plugin's icon (through the panel), or its monogram. */
function PluginIcon({ plugin, large }: { plugin: { name: string; icon_url?: string | null }; large?: boolean }) {
  const [broken, setBroken] = useState(false);
  if (!plugin.icon_url || broken) return <Monogram name={plugin.name} large={large} />;
  return <img className={`plugin-icon ${large ? "lg" : ""}`} src={plugin.icon_url} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

/** "Made for your country", or the countries a plugin is made for. */
function Countries({ plugin }: { plugin: { countries?: string[]; local?: boolean | null } }) {
  if (plugin.local) return <Tag tone="accent" icon={<MapPin />}>Made for your country</Tag>;
  if (!plugin.countries?.length) return null;
  const shown = plugin.countries.slice(0, 3).join(", ") + (plugin.countries.length > 3 ? ` +${plugin.countries.length - 3}` : "");
  return <Tag icon={<MapPin />}>{shown}</Tag>;
}

/** A new key for each press of Buy; the same key is sent again if that one request is retried. */
function newIdempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(18));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const REASON: Record<string, string> = {
  card_declined: "The card was declined",
  insufficient_funds: "The card was declined (insufficient funds)",
  expired_card: "The card has expired",
  authentication_required: "The bank asked to confirm the payment",
  checkout_expired: "The payment page expired",
  checkout_failed: "The payment did not go through",
  link_changed: "The server's account changed meanwhile",
  payment_service_unreachable: "The payment service could not be reached",
};
const reasonText = (reason: string | null) => (reason ? REASON[reason] ?? reason.replace(/_/g, " ") : "");

// ---------------------------------------------------------------- the running plugin job, then the restart

interface Work {
  jobId: string;
  name: string;
  verb: string;
}

function useInstaller() {
  const client = useQueryClient();
  const toast = useToast();
  const [work, setWork] = useState<Work | null>(null);
  const start = (job: Job, name: string, verb = "installed") => setWork({ jobId: job.id, name, verb });
  const finish = async (job: Job) => {
    if (!work) return;
    if (job.status === "failed") {
      toast("error", `${work.name} was not ${work.verb}`, job.error ?? "Open the details to see why.");
      return;
    }
    toast("info", "Restarting the panel", "Instances keep running; this takes a few seconds");
    const back = await waitForBackend();
    await client.invalidateQueries();
    setWork(null);
    if (back) toast("success", `${work.name} is ${work.verb}`);
    else toast("error", "The panel is slow to come back", "Reload the page in a minute.");
  };
  return { work, start, finish, clear: () => setWork(null) };
}

function WorkCard({ work, onFinished, onClear }: { work: Work; onFinished: (job: Job) => void; onClear: () => void }) {
  const { data: job } = useJob(work.jobId);
  const [details, setDetails] = useState(false);
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (job && (job.status === "success" || job.status === "failed") && reported.current !== job.status) {
      reported.current = job.status;
      onFinished(job);
    }
  }, [job, onFinished]);
  return (
    <div className="card pad rise stack-sm">
      <div className="row">
        <Puzzle className="faint" />
        <b className="spacer truncate">{work.name}</b>
        <Button size="sm" variant="ghost" onClick={() => setDetails(true)}>Details</Button>
        {job?.status === "failed" && <Button size="sm" variant="ghost" onClick={onClear}>Dismiss</Button>}
      </div>
      {job ? (
        job.status === "success" ? (
          <div className="row small muted"><span className="spinner" /> Restarting the panel to load it</div>
        ) : (
          <JobLine job={job} />
        )
      ) : (
        <Skeleton height={24} />
      )}
      {job?.status === "failed" && job.error && <Callout tone="danger">{job.error}</Callout>}
      {details && <JobDrawer id={work.jobId} onClose={() => setDetails(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------- catalogue

const ACTION_TAG: Record<CatalogPlugin["action"], [string, "positive" | "accent" | "caution" | undefined]> = {
  install: ["", undefined],
  update: ["Update available", "accent"],
  installed: ["Installed", "positive"],
  buy: ["", undefined],
  renew: ["Licence ended", "caution"],
  incompatible: ["Needs a newer Sudoo.sh", "caution"],
};

function PluginCard({ plugin, onOpen }: { plugin: CatalogPlugin; onOpen: () => void }) {
  const [label, tone] = ACTION_TAG[plugin.action] ?? ["", undefined];
  return (
    <button type="button" className="card link plugin-card" onClick={onOpen}>
      <div className="pc-head">
        <PluginIcon plugin={plugin} />
        <div className="pc-titles">
          <span className="pc-name truncate">{plugin.name}</span>
          <PublisherBadge publisher={plugin.publisher} />
        </div>
      </div>
      <p className="pc-text">{plugin.description}</p>
      <div className="pc-foot">
        <Tag tone={plugin.tier === "free" ? "positive" : undefined}>{priceOf(plugin)}</Tag>
        <span className="row xsmall faint">
          <Star /> {plugin.rating_count ? plugin.avg_rating.toFixed(1) : "—"}
        </span>
        <span className="xsmall faint">{number(plugin.install_count)} {plugin.install_count === 1 ? "install" : "installs"}</span>
        <span className="spacer" />
        {label ? <Tag tone={tone}>{label}</Tag> : <Countries plugin={plugin} />}
      </div>
    </button>
  );
}

function PluginSheet({
  plugin,
  installed,
  busy,
  onClose,
  onStarted,
}: {
  plugin: CatalogPlugin;
  installed?: InstalledPlugin;
  busy: boolean;
  onClose: () => void;
  onStarted: (job: Job, name: string, verb?: string) => void;
}) {
  const { data: detail } = useCatalogPlugin(plugin.id);
  const can = useCan();
  const manage = can("settings.manage");
  const paid = plugin.tier === "paid" && (plugin.action === "buy" || plugin.action === "renew");
  const plans = plugin.plans?.length ? plugin.plans : detail?.plans ?? [];
  const { data: billing, error: billingError } = useBilling(manage && paid);
  const toast = useToast();
  const client = useQueryClient();
  const [plan, setPlan] = useState<string>("");
  const [step, setStep] = useState<"idle" | "working" | "paying">("idle");
  const [session, setSession] = useState<CheckoutSession | null>(null);
  const [ended, setEnded] = useState<string | null>(null);
  const chosen = plans.find((p) => p.id === plan) ?? plans[0];
  const repair = installed?.status === "modified";
  const action = repair ? "install" : plugin.action;

  const install = async (verb = "installed") => {
    const job = await api.post<Job>("/plugins", { id: plugin.id });
    onStarted(job, plugin.name, verb);
    onClose();
  };

  // a checkout session the owner pays on app.sudoo.sh: follow it every 4 seconds and when this tab gets the focus
  // back, while it is open, processing or on Stripe; install once it succeeded
  useEffect(() => {
    if (step !== "paying" || !session) return;
    let stop = false;
    let checking = false;
    const check = async () => {
      if (stop || checking) return;
      checking = true;
      try {
        const current = await api.get<CheckoutSession>(`/marketplace/checkout-sessions/${session.id}`);
        if (stop) return;
        setSession(current);
        if (current.status === "succeeded") {
          stop = true;
          toast("success", "Payment received", `Installing ${plugin.name}`);
          void client.invalidateQueries({ queryKey: keys.purchases });
          try {
            await install();
          } catch (err) {
            toast("error", `Paid, but ${plugin.name} is not installed yet`, `${errorText(err)} Install it from the Marketplace.`);
            setStep("idle");
          }
        } else if (current.status === "expired" || current.status === "cancelled" || current.status === "failed") {
          stop = true;
          setEnded(
            current.status === "expired"
              ? "The payment page expired before it was paid. Nothing was charged."
              : current.status === "cancelled"
                ? "The purchase was cancelled on app.sudoo.sh. Nothing was charged."
                : `The payment did not go through${current.reason ? `: ${reasonText(current.reason).toLowerCase()}` : ""}.`,
          );
          setStep("idle");
        }
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 503)) {
          stop = true;
          toast("error", "Lost track of the payment", errorText(err));
          setStep("idle");
        }
      } finally {
        checking = false;
      }
    };
    const timer = setInterval(() => void check(), 4000);
    const focus = () => document.visibilityState === "visible" && void check();
    document.addEventListener("visibilitychange", focus);
    window.addEventListener("focus", focus);
    return () => {
      stop = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", focus);
      window.removeEventListener("focus", focus);
    };
  }, [step, session?.id]);

  const installNow = async () => {
    setStep("working");
    try {
      await install(action === "update" ? "updated" : "installed");
    } catch (err) {
      toast("error", `${plugin.name} was not installed`, errorText(err));
      setStep("idle");
    }
  };

  const buy = async () => {
    if (!chosen) return;
    setStep("working");
    setEnded(null);
    // opened now, while the click still counts, so the browser does not block it; sent to the payment page once
    // the hub answers
    const tab = window.open("about:blank", "_blank");
    try {
      const body = { plugin_id: plugin.id, plan_id: chosen.id, idempotency_key: newIdempotencyKey() };
      const opened = await api.post<CheckoutSession>("/marketplace/checkout-sessions", body);
      if (opened.status === "succeeded") {
        tab?.close();
        setSession(opened);
        setStep("paying");
        return;
      }
      if (!opened.url) throw new Error("The marketplace did not send a payment page.");
      if (tab) {
        tab.opener = null;
        tab.location.href = opened.url;
      } else {
        window.open(opened.url, "_blank", "noopener");
      }
      setSession(opened);
      setStep("paying");
    } catch (err) {
      tab?.close();
      toast("error", "Not bought", errorText(err));
      setStep("idle");
    }
  };

  const button = () => {
    if (!manage) return null;
    if (action === "installed") return <Tag tone="positive">Installed · v{installed?.version ?? plugin.installed_version}</Tag>;
    if (action === "incompatible") return <Button disabled>Needs a newer Sudoo.sh</Button>;
    if (action === "install" || action === "update")
      return (
        <Button variant="primary" icon={<Download />} loading={step === "working"} disabled={busy} onClick={installNow}>
          {repair ? "Install again" : action === "update" ? `Update to v${plugin.compatible_version?.version ?? ""}` : "Install"}
        </Button>
      );
    return (
      <Button variant="primary" icon={<ShoppingBag />} loading={step === "working"} disabled={busy || !billing?.can_buy || !chosen || step === "paying"} onClick={buy}>
        {action === "renew" ? "Renew on app.sudoo.sh" : "Buy on app.sudoo.sh"}
      </Button>
    );
  };

  const waiting =
    session?.status === "processing"
      ? "The payment is being processed."
      : session?.status === "open" && session.reason
        ? `${reasonText(session.reason)}. Try another card in the other tab.`
        : "Waiting for payment in the other tab.";

  const version = plugin.compatible_version ?? plugin.latest_version;
  return (
    <Modal
      wide
      title={<span className="row"><PluginIcon plugin={plugin} large /> {plugin.name}</span>}
      description={<PublisherBadge publisher={plugin.publisher} />}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          {button()}
        </>
      }
    >
      <div className="stack">
        <p>{plugin.description}</p>
        <div className="row-wrap">
          <Tag>{TYPE_LABEL[plugin.type] ?? plugin.type}</Tag>
          {version && <Tag mono>v{version.version}</Tag>}
          {version?.min_sudoo_version && <Tag mono>Sudoo.sh {version.min_sudoo_version}+</Tag>}
          <Tag tone={plugin.tier === "free" ? "positive" : undefined}>{priceOf({ ...plugin, plans })}</Tag>
          <Countries plugin={plugin} />
        </div>
        {(detail?.permissions?.length ?? 0) > 0 && (
          <Field label="It asks to">
            <div className="row-wrap">{detail!.permissions.map((p) => <Tag key={p} mono>{p}</Tag>)}</div>
          </Field>
        )}
        {(plugin.requires?.length ?? 0) > 0 && (
          <Field label="It needs">
            <div className="row-wrap">{plugin.requires.map((r) => <Tag key={r.id} mono>{r.id} {r.version ?? ""}</Tag>)}</div>
          </Field>
        )}
        {plugin.license?.perpetual ? (
          <p className="small muted">Licence {plugin.license.state}, perpetual.</p>
        ) : plugin.license?.expires_at ? (
          <p className="small muted">Licence {plugin.license.state}, ends {day(plugin.license.expires_at)}.</p>
        ) : null}
        {paid && manage && (
          <>
            {plans.length > 0 && (
              <Field label="Plan">
                <div className="plan-list" role="radiogroup">
                  {plans.map((p) => (
                    <label key={p.id} className="plan">
                      <input type="radio" name="plan" value={p.id} checked={chosen?.id === p.id} onChange={() => setPlan(p.id)} disabled={step === "paying"} />
                      <span className="stack-sm" style={{ gap: 0 }}>
                        <span className="plan-price">{PLAN_NAME[p.kind] ?? p.kind}</span>
                        <span className="small muted">{planPrice(p)}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </Field>
            )}
            {chosen && (
              <p className="small muted">
                {chosen.perpetual
                  ? "Paid once, a licence that does not expire."
                  : chosen.kind === "fixed_term"
                    ? "Paid once, for the term."
                    : "Renewed until it is cancelled on app.sudoo.sh."}{" "}
                The account owner pays on app.sudoo.sh, in a new tab; this panel never charges anything.
              </p>
            )}
            {billingError && <Callout tone="warning">{errorText(billingError)}</Callout>}
            {billing?.reason === "link_required" && (
              <Callout tone="info">
                <div className="stack-sm">
                  <span>Paid plugins belong to an account on app.sudoo.sh. Link this panel to yours first.</span>
                  <LinkForm onLinked={() => void client.invalidateQueries({ queryKey: ["marketplace", "billing"] })} />
                </div>
              </Callout>
            )}
            {billing?.reason === "fingerprint_mismatch" && (
              <Callout tone="danger">
                This server is flagged (it reported from another machine), so it cannot buy plugins.{" "}
                {billing.manage_url && <a href={billing.manage_url} target="_blank" rel="noreferrer noopener">Accept this machine on app.sudoo.sh <ExternalLink /></a>}
              </Callout>
            )}
            {billing?.reason === "payments_disabled" && <Callout tone="warning">Payments are switched off on the marketplace right now.</Callout>}
            {billing?.reason === "installation_suspended" && <Callout tone="danger">This panel is suspended on the marketplace. Contact Sudoo.sh support.</Callout>}
            {step === "paying" && session && (
              <Callout tone={session.status === "open" && session.reason ? "warning" : "info"}>
                <div className="stack-sm">
                  <div className="row"><span className="spinner" /> {waiting} The plugin installs as soon as it is paid.</div>
                  {session.url && (
                    <a href={session.url} target="_blank" rel="noreferrer noopener">Open the payment page again <ExternalLink /></a>
                  )}
                </div>
              </Callout>
            )}
            {ended && step === "idle" && (
              <Callout tone="warning">
                <div className="stack-sm">
                  <span>{ended}</span>
                  <span className="small">Press the button again to start a new purchase.</span>
                </div>
              </Callout>
            )}
          </>
        )}
        {!manage && <p className="small muted">Only a super admin can install or buy plugins.</p>}
        <p className="xsmall faint">Every package is signed by the marketplace and checked by this panel before it is installed. The plugin's code stays on the server and is never shown.</p>
      </div>
    </Modal>
  );
}

function Catalogue({ installed, busy, onStarted }: { installed: InstalledPlugin[]; busy: boolean; onStarted: (job: Job, name: string, verb?: string) => void }) {
  const { data: status } = useMarketplace();
  const usable = !!status?.enabled;
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [tier, setTier] = useState<"" | "free" | "paid">("");
  const [sort, setSort] = useState("trusted");
  const [open, setOpen] = useState<CatalogPlugin | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setQ(typed.trim()), 250);
    return () => clearTimeout(timer);
  }, [typed]);
  const query = useMemo(() => {
    const params = new URLSearchParams({ sort, limit: "60" });
    if (q) params.set("q", q);
    if (type) params.set("type", type);
    if (tier) params.set("tier", tier);
    return params.toString();
  }, [q, type, tier, sort]);
  const { data: plugins, error, isPending } = useCatalog(query, usable);
  const { data: categories } = useCategories(usable);
  const { data: recommended } = useRecommendations(usable);
  const byId = Object.fromEntries(installed.map((p) => [p.id, p]));
  const browsing = !q && !type && !tier;
  /** A suggested plugin as the sheet needs it: the catalogue's entry when loaded, else built from the suggestion. */
  const openSuggestion = (pick: Recommendation) => {
    const known = plugins?.find((p) => p.id === pick.plugin.id);
    setOpen(
      known ?? {
        ...pick.plugin,
        plans: [],
        latest_version: null,
        compatible_version: null,
        installed_version: null,
        license: null,
        action: pick.plugin.tier === "free" ? "install" : "buy",
      },
    );
  };

  if (!usable) return null;
  return (
    <div className="stack">
      <div className="toolbar">
        <div className="input-group">
          <Search />
          <input className="input" placeholder="Search plugins" aria-label="Search plugins" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </div>
        <select className="select" style={{ width: "auto" }} aria-label="Category" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All categories</option>
          {(categories ?? []).map((c) => (
            <option key={c.type} value={c.type}>{TYPE_LABEL[c.type] ?? c.type} ({c.count})</option>
          ))}
        </select>
        <Segmented value={tier} onChange={setTier} options={[{ value: "", label: "All" }, { value: "free", label: "Free" }, { value: "paid", label: "Paid" }]} />
        <span className="spacer" />
        <select className="select" style={{ width: "auto" }} aria-label="Order" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="trusted">Official and verified first</option>
          <option value="popular">Most installed</option>
          <option value="rating">Best rated</option>
          <option value="newest">Newest</option>
          <option value="name">Name</option>
        </select>
      </div>
      {browsing && !!recommended?.length && (
        <section className="stack-sm rise" aria-labelledby="recommended">
          <h2 id="recommended" className="row small"><Sparkles className="faint" /> Recommended</h2>
          <div className="reco-row">
            {recommended.map((pick) => (
              <button key={pick.plugin.id} type="button" className="card link plugin-card" onClick={() => openSuggestion(pick)}>
                <div className="pc-head">
                  <PluginIcon plugin={pick.plugin} />
                  <div className="pc-titles">
                    <span className="pc-name truncate">{pick.plugin.name}</span>
                    <PublisherBadge publisher={pick.plugin.publisher} />
                  </div>
                </div>
                <span className="reco-why">{pick.reasons[0] ?? "Suggested for this server"}</span>
                <div className="pc-foot">
                  <Tag tone={pick.plugin.tier === "free" ? "positive" : undefined}>{pick.plugin.tier === "free" ? "Free" : "Paid"}</Tag>
                  <span className="spacer" />
                  <Countries plugin={pick.plugin} />
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
      {isPending ? (
        <div className="plugin-grid">{[0, 1, 2].map((i) => <Skeleton key={i} height={168} />)}</div>
      ) : error ? (
        <Callout tone="warning">{errorText(error)}</Callout>
      ) : !plugins?.length ? (
        <div className="card"><Empty icon={<Puzzle />} title="No plugins found">Try another word or category.</Empty></div>
      ) : (
        <div className="plugin-grid rise">
          {plugins.map((plugin) => (
            <PluginCard key={plugin.id} plugin={plugin} onOpen={() => setOpen(plugin)} />
          ))}
        </div>
      )}
      {open && <PluginSheet plugin={open} installed={byId[open.id]} busy={busy} onClose={() => setOpen(null)} onStarted={onStarted} />}
    </div>
  );
}

// ---------------------------------------------------------------- installed

const STATUS: Record<InstalledPlugin["status"], [string, string]> = {
  active: ["online", "Running"],
  disabled: ["stopped", "Switched off"],
  modified: ["failed", "Files changed"],
  blocked: ["failed", "Refused by the marketplace"],
  withheld: ["failed", "Withheld (server flagged)"],
  switched_off: ["paused", "Stopped (licence)"],
  unlicensed: ["paused", "No licence"],
};
const PHASE: Record<string, [string, "positive" | "caution" | "negative" | undefined]> = {
  active: ["Licensed", "positive"],
  perpetual: ["Licensed for good", "positive"],
  withheld: ["Withheld", "negative"],
  expiring: ["Ends soon", "caution"],
  grace: ["In grace period", "caution"],
  ended: ["Licence ended", "negative"],
  no_lease: ["Marketplace unreachable", "negative"],
  unlicensed: ["No licence", "negative"],
};

function Installed({ plugins, busy, onStarted }: { plugins: InstalledPlugin[]; busy: boolean; onStarted: (job: Job, name: string, verb?: string) => void }) {
  const can = useCan();
  const toast = useToast();
  const client = useQueryClient();
  const [removing, setRemoving] = useState<InstalledPlugin | null>(null);
  const [confirm, setConfirm] = useState("");
  const manage = can("settings.manage");

  const switchTo = async (plugin: InstalledPlugin, on: boolean) => {
    try {
      await api.post(`/plugins/${plugin.id}/${on ? "enable" : "disable"}`);
      toast("info", `${plugin.name} is switched ${on ? "on" : "off"}`, "The panel restarts to apply it");
      await waitForBackend();
      await client.invalidateQueries();
    } catch (error) {
      toast("error", "Not changed", errorText(error));
    }
  };
  const update = async (plugin: InstalledPlugin) => {
    try {
      onStarted(await api.post<Job>(`/plugins/${plugin.id}/update`), plugin.name, "updated");
    } catch (error) {
      toast("error", "Not updated", errorText(error));
    }
  };
  const uninstall = async () => {
    if (!removing) return;
    try {
      onStarted(await api.del<Job>(`/plugins/${removing.id}`, { confirm }), removing.name, "uninstalled");
      setRemoving(null);
      setConfirm("");
    } catch (error) {
      toast("error", "Not uninstalled", errorText(error));
    }
  };

  if (!plugins.length)
    return (
      <div className="card">
        <Empty icon={<Puzzle />} title="No plugins yet">Plugins from the marketplace add features to the panel: sign-in methods, mailers, backup destinations and more.</Empty>
      </div>
    );
  return (
    <div className="card rise">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>Plugin</th><th>Version</th><th>Status</th><th>Licence</th><th /></tr>
          </thead>
          <tbody>
            {plugins.map((p) => {
              const [cls, label] = STATUS[p.status] ?? ["unknown", p.status];
              const phase = p.licence?.phase ? PHASE[p.licence.phase] : null;
              return (
                <tr key={p.id}>
                  <td>
                    <div className="row">
                      <PluginIcon plugin={p} />
                      <div style={{ minWidth: 0 }}>
                        <div className="truncate">{p.name}</div>
                        <div className="xsmall faint"><PublisherBadge publisher={p.publisher} /></div>
                      </div>
                    </div>
                  </td>
                  <td className="nowrap">
                    <span className="mono small">v{p.version}</span>
                    {p.update_available && manage && (
                      <> <Button size="sm" variant="soft" disabled={busy} onClick={() => update(p)}>Update to v{p.latest_version}</Button></>
                    )}
                  </td>
                  <td>
                    <Status status={p.restart_pending ? "starting" : cls} label={p.restart_pending ? "Waiting for a restart" : label} />
                  </td>
                  <td className="small">
                    {p.tier === "free" ? (
                      <span className="faint">Free</span>
                    ) : (
                      <div className="stack-sm" style={{ gap: 2, alignItems: "flex-start" }}>
                        {phase && <Tag tone={phase[1]}>{phase[0]}</Tag>}
                        {p.licence?.expires_at && <span className="xsmall faint">Ends {day(p.licence.expires_at)}{p.licence.grace_until ? ` · stops ${day(p.licence.grace_until)}` : ""}</span>}
                        {p.licence?.perpetual && <span className="xsmall faint">One-time licence, no renewal</span>}
                      </div>
                    )}
                  </td>
                  <td className="actions">
                    {manage && (
                      <Menu trigger={(toggle) => <Button size="sm" variant="ghost" onClick={toggle} disabled={busy}>Manage</Button>}>
                        {(close) => (
                          <>
                            {p.enabled ? (
                              <button onClick={() => { close(); void switchTo(p, false); }}>Switch off</button>
                            ) : (
                              <button disabled={p.status === "modified"} onClick={() => { close(); void switchTo(p, true); }}>Switch on</button>
                            )}
                            <hr />
                            <button className="danger" onClick={() => { close(); setRemoving(p); }}>
                              <Trash2 /> Uninstall
                            </button>
                          </>
                        )}
                      </Menu>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {removing && (
        <Modal
          title={`Uninstall ${removing.name}`}
          description="The panel's data is backed up first; then the plugin's files are removed and the panel restarts."
          onClose={() => setRemoving(null)}
          footer={
            <>
              <Button onClick={() => setRemoving(null)}>Cancel</Button>
              <Button variant="danger" icon={<Trash2 />} disabled={confirm !== removing.id} onClick={uninstall}>Uninstall</Button>
            </>
          }
        >
          <Field label={<>Type <code>{removing.id}</code> to confirm</>}>
            <input className="input mono" autoFocus value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </Field>
          {removing.tier === "paid" && <p className="small muted" style={{ marginTop: 12 }}>Uninstalling does not cancel its subscription: do that on app.sudoo.sh.</p>}
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- purchases

const PURCHASE_STATUS: Record<string, [string, "positive" | "caution" | "negative" | undefined]> = {
  succeeded: ["Paid", "positive"],
  open: ["Waiting for payment", "caution"],
  processing: ["Processing", "caution"],
  checkout_required: ["Paying on Stripe", "caution"],
  failed: ["Failed", "negative"],
  cancelled: ["Cancelled", undefined],
  expired: ["Expired", undefined],
};

function Purchases() {
  const { data: status } = useMarketplace();
  const usable = !!status?.enabled;
  const { data: receipts, error: receiptsError, isPending: receiptsPending } = useReceipts(usable);
  const { data: purchases, error, isPending } = usePurchases(usable);
  const { data: billing } = useBilling(usable);
  if (!usable) return null;
  return (
    <div className="stack">
      <div className="card rise">
        <div className="card-head">
          <Receipt />
          <div className="spacer">
            <h2>Receipts</h2>
            <div className="sub">Payments and renewals of this server's plugins, and credit notes for refunds</div>
          </div>
          {billing?.manage_url && (
            <a className="btn sm ghost" href={billing.manage_url} target="_blank" rel="noreferrer noopener">
              app.sudoo.sh <ExternalLink />
            </a>
          )}
          {!!receipts?.length && (
            <a className="btn sm" href="/api/v1/marketplace/receipts?format=csv" download>
              <FileDown /> Export CSV
            </a>
          )}
        </div>
        {receiptsPending ? (
          <div className="card-body"><Skeleton height={100} /></div>
        ) : receiptsError ? (
          <div className="card-body"><Callout tone="warning">{errorText(receiptsError)}</Callout></div>
        ) : !receipts?.length ? (
          <Empty icon={<Receipt />} title="No receipts yet">Paid plugins bought for this server appear here.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Number</th><th>Date</th><th>Plugin</th><th>Plan</th><th>Asked by</th><th className="num">Total</th></tr>
              </thead>
              <tbody>
                {receipts.map((r) => (
                  <tr key={r.id}>
                    <td className="mono small nowrap">{r.number}{r.kind === "credit_note" && <span className="faint"> · credit note</span>}</td>
                    <td className="small nowrap">{day(r.issued_at)}</td>
                    <td>{r.plugin_name ?? r.plugin_id}{r.payment_kind === "renewal" && <span className="faint small"> · renewal</span>}</td>
                    <td className="small">{r.plan_kind ? PLAN_NAME[r.plan_kind] ?? r.plan_kind : "—"}</td>
                    <td className="small muted">{r.requested_by_name ?? "—"}</td>
                    <td className="num">{money(r.kind === "credit_note" ? -Math.abs(r.total_cents) : r.total_cents, r.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card rise">
        <div className="card-head">
          <ShoppingBag />
          <div className="spacer">
            <h2>Purchases</h2>
            <div className="sub">Every purchase asked for from this server (paid by the account owner on app.sudoo.sh), and how it ended</div>
          </div>
          {!!purchases?.length && (
            <a className="btn sm" href="/api/v1/marketplace/checkout-sessions?format=csv" download>
              <FileDown /> Export CSV
            </a>
          )}
        </div>
        {isPending ? (
          <div className="card-body"><Skeleton height={100} /></div>
        ) : error ? (
          <div className="card-body"><Callout tone="warning">{errorText(error)}</Callout></div>
        ) : !purchases?.length ? (
          <Empty icon={<ShoppingBag />} title="No purchases yet">Buy a paid plugin from the Marketplace tab.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Date</th><th>Plugin</th><th>Plan</th><th>Asked by</th><th>Status</th><th className="num">Amount</th></tr>
              </thead>
              <tbody>
                {purchases.map((p) => {
                  const [label, tone] = PURCHASE_STATUS[p.status ?? ""] ?? [p.status ?? "—", undefined];
                  return (
                    <tr key={p.id}>
                      <td className="small nowrap">{day(p.created_at)} <span className="faint">· {ago(p.created_at)}</span></td>
                      <td>{p.plugin_name}</td>
                      <td className="small">{p.plan_kind ? PLAN_NAME[p.plan_kind] ?? p.plan_kind : "—"}</td>
                      <td className="small muted">{p.requested_by?.name ?? "—"}</td>
                      <td>
                        <div className="stack-sm" style={{ gap: 2, alignItems: "flex-start" }}>
                          <Tag tone={tone}>{label}</Tag>
                          {p.reason && p.status !== "succeeded" && <span className="xsmall faint">{reasonText(p.reason)}</span>}
                          {p.receipt_number && <span className="xsmall faint mono">{p.receipt_number}</span>}
                          {p.url && <a className="xsmall" href={p.url} target="_blank" rel="noreferrer noopener">Payment page <ExternalLink /></a>}
                        </div>
                      </td>
                      <td className="num">{money(p.amount_cents, p.currency)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the page

const TABS = [
  { id: "", label: "Marketplace" },
  { id: "installed", label: "Installed" },
  { id: "purchases", label: "Purchases" },
];

export function PluginsPage() {
  const { tab = "" } = useParams();
  const navigate = useNavigate();
  const { data: status } = useMarketplace();
  const { data: installed, isPending } = usePlugins();
  const installer = useInstaller();
  const problem = marketplaceProblem(status);
  const updates = installed?.filter((p) => p.update_available).length ?? 0;
  const started = (job: Job, name: string, verb?: string) => {
    installer.start(job, name, verb);
    if (tab !== "installed") navigate("/plugins/installed", { viewTransition: true });
  };
  return (
    <Page>
      <PageHead title="Plugins">
        Add features from the Sudoo.sh marketplace. Every package is signed by the marketplace and checked here before it is installed.
      </PageHead>
      {problem && <Callout tone={problem.tone}>{problem.text}</Callout>}
      {installer.work && <WorkCard work={installer.work} onFinished={installer.finish} onClear={installer.clear} />}
      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink key={t.id} to={`/plugins${t.id ? `/${t.id}` : ""}`} end viewTransition className={({ isActive }) => (isActive ? "active" : "")}>
            {t.label}
            {t.id === "installed" && !!installed?.length && <span className="faint tabular">{installed.length}</span>}
            {t.id === "installed" && updates > 0 && <Tag tone="accent">{updates} {updates === 1 ? "update" : "updates"}</Tag>}
          </NavLink>
        ))}
      </nav>
      <div className="rise" key={tab}>
        {tab === "installed" ? (
          isPending ? <Skeleton height={160} /> : <Installed plugins={installed ?? []} busy={!!installer.work} onStarted={started} />
        ) : tab === "purchases" ? (
          <Purchases />
        ) : (
          <Catalogue installed={installed ?? []} busy={!!installer.work} onStarted={started} />
        )}
      </div>
    </Page>
  );
}
