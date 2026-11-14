// The connection to the Sudoo.sh marketplace: shown on Settings (Marketplace) and inside the Plugins page.

import { useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Link2, LogOut, RefreshCcw } from "lucide-react";
import { useState } from "react";
import { api, errorText } from "@/api/client";
import { keys, useMarketplace, usePlugins } from "@/api/queries";
import type { MarketplaceStatus, Publisher } from "@/api/types";
import { ago, dateTime } from "@/lib/format";
import { useCan } from "./Shell";
import { Mark } from "./ui/Brand";
import { Button, Callout, Field, Skeleton, Tag } from "./ui/basics";
import { Modal, useToast } from "./ui/overlay";

/** Official (Sudoo.sh's own plugins) or Verified (Sudoo.sh checked who the publisher is). */
export function PublisherBadge({ publisher }: { publisher: Publisher | null }) {
  if (!publisher) return <span className="faint">Unknown publisher</span>;
  return (
    <span className="publisher">
      <span className="truncate">{publisher.name}</span>
      {publisher.official ? (
        <Tag tone="accent" icon={<Mark size={12} />}>Official</Tag>
      ) : publisher.verified ? (
        <span className="verified" title="Verified publisher: Sudoo.sh checked who they are" aria-label="Verified publisher">
          <BadgeCheck />
        </span>
      ) : null}
    </span>
  );
}

/** Why the marketplace cannot be used right now, in the person's words; null when it can. */
export function marketplaceProblem(status: MarketplaceStatus | undefined): { tone: "warning" | "danger"; text: string } | null {
  if (!status) return null;
  if (!status.enabled) return { tone: "warning", text: "The marketplace is switched off on this panel. A super admin can switch it on in Settings, Marketplace." };
  if (status.hub_status === "integrity_violation")
    return { tone: "danger", text: "The marketplace refuses this panel: its core files differ from the released version. Every plugin is switched off until the panel is reinstalled." };
  if (status.hub_status === "installation_suspended")
    return { tone: "danger", text: "This panel is suspended on the marketplace, so every plugin is switched off. Contact Sudoo.sh support." };
  if (status.error_code === "unverified")
    return {
      tone: "danger",
      text: "The marketplace's last answer was not signed by a key this panel trusts, so it was ignored. Installed plugins keep working; the panel tries again on its own. If this lasts, tell Sudoo.sh support.",
    };
  if (status.flags?.includes("fingerprint_mismatch"))
    return {
      tone: "danger",
      text: "This server is flagged: it reported from another machine than the one it was registered on, so its paid plugins are withheld. The account owner must accept this machine on app.sudoo.sh (Servers), or revoke its key if it is a copy.",
    };
  if (status.reachable === false)
    return {
      tone: "warning",
      text: `The marketplace cannot be reached right now${status.lease_valid ? "" : ", and the panel's last lease has ended: paid plugins stop when their offline time runs out"}. Instances and installed plugins keep working; the panel tries again every few minutes.`,
    };
  return null;
}

export function LinkForm({ onLinked }: { onLinked?: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const link = async () => {
    setBusy(true);
    try {
      const linked = await api.post<{ account_name: string }>("/marketplace/link", { code: code.trim() });
      toast("success", "Panel linked", `It now belongs to ${linked.account_name} on app.sudoo.sh`);
      setCode("");
      await client.invalidateQueries({ queryKey: keys.marketplace });
      onLinked?.();
    } catch (error) {
      toast("error", "Not linked", errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Field label="Link code" hint="On app.sudoo.sh, open Servers and choose Link a server. The code works once, for 15 minutes.">
      <div className="row">
        <input
          className="input mono"
          autoComplete="one-time-code"
          spellCheck={false}
          placeholder="ABCD-1234"
          maxLength={20}
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && code.trim().length >= 8 && link()}
        />
        <Button variant="primary" icon={<Link2 />} loading={busy} disabled={code.trim().length < 8} onClick={link}>
          Link
        </Button>
      </div>
    </Field>
  );
}

/** Settings, Marketplace: the connection, the lease, and linking to an account. */
export function MarketplaceSettings() {
  const { data: status, isPending } = useMarketplace();
  const can = useCan();
  const client = useQueryClient();
  const toast = useToast();
  const [sending, setSending] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const { data: installed } = usePlugins();
  if (isPending) return <div className="card-body"><Skeleton height={120} /></div>;
  if (!status) return null;
  const problem = marketplaceProblem(status);
  const heartbeat = async () => {
    setSending(true);
    try {
      await api.post("/marketplace/heartbeat");
      toast("success", "The marketplace answered");
    } catch (error) {
      toast("error", "No answer", errorText(error));
    } finally {
      await client.invalidateQueries({ queryKey: keys.marketplace });
      setSending(false);
    }
  };
  const paid = (installed ?? []).filter((p) => p.tier === "paid");
  const logOut = async () => {
    setLoggingOut(true);
    try {
      await api.post("/marketplace/unlink", { confirm: true });
      toast("success", "Logged out of the account", paid.length ? "The paid plugins are being removed after a backup" : undefined);
      setLeaving(false);
    } catch (error) {
      toast("error", "Still logged in", errorText(error));
    } finally {
      await client.invalidateQueries({ queryKey: keys.marketplace });
      await client.invalidateQueries({ queryKey: keys.plugins });
      setLoggingOut(false);
    }
  };
  return (
    <div className="card-body stack">
      {problem && <Callout tone={problem.tone}>{problem.text}</Callout>}
      {status.key_revoked_at && !status.linked?.account_name && (
        <Callout tone="warning">This server's key was revoked on app.sudoo.sh, so the panel registered again with a new identity. Link it to your account again to use paid plugins.</Callout>
      )}
      {status.removing_paid_plugins && <Callout tone="info">The panel is removing this server's paid plugins (it was logged out of its account). A backup is taken first.</Callout>}
      <dl className="dl">
        <dt>Hub</dt>
        <dd className="mono small">{status.hub_url}</dd>
        <dt>This installation</dt>
        <dd className="mono small">{status.installation_id ?? "—"}</dd>
        <dt>Last heartbeat</dt>
        <dd>
          {status.last_heartbeat_at ? `${ago(status.last_heartbeat_at)} · ${dateTime(status.last_heartbeat_at)}` : "None yet"}
        </dd>
        <dt>Lease</dt>
        <dd>
          {status.lease_valid ? (
            <>
              Valid until {dateTime(status.lease_expires_at)}
              {status.lease_ending_soon && <> <Tag tone="caution">ends soon</Tag></>}
            </>
          ) : (
            <span className="muted">None: paid plugins cannot run until the next heartbeat passes</span>
          )}
        </dd>
        <dt>Account</dt>
        <dd>{status.linked?.account_name ? <>Linked to <b>{status.linked.account_name}</b></> : <span className="muted">Not linked. Free plugins need no account; paid ones do</span>}</dd>
      </dl>
      {can("settings.manage") && status.enabled && (
        <>
          {!status.linked?.account_name && <LinkForm />}
          <div className="row">
            <Button size="sm" icon={<RefreshCcw />} loading={sending} onClick={heartbeat}>
              Send a heartbeat now
            </Button>
            {status.linked?.account_name && (
              <Button size="sm" variant="ghost" icon={<LogOut />} onClick={() => setLeaving(true)}>
                Log out of the account
              </Button>
            )}
          </div>
        </>
      )}
      {leaving && (
        <Modal
          title="Log out of the account?"
          description={`This server stops belonging to ${status.linked?.account_name ?? "its account"} on app.sudoo.sh.`}
          onClose={() => setLeaving(false)}
          footer={
            <>
              <Button onClick={() => setLeaving(false)}>Cancel</Button>
              <Button variant="danger" icon={<LogOut />} loading={loggingOut} onClick={logOut}>Log out and remove paid plugins</Button>
            </>
          }
        >
          <div className="stack-sm">
            <p>
              <b>Paid plugins are removed.</b> Their licences for this server are revoked at once and subscriptions end without a refund.
              The panel backs up its data (and the instances those plugins can change) first.
            </p>
            {paid.length > 0 ? (
              <div className="row-wrap">{paid.map((p) => <Tag key={p.id}>{p.name}</Tag>)}</div>
            ) : (
              <p className="small muted">No paid plugin is installed.</p>
            )}
            <p className="small muted">The panel, free plugins and every instance keep running. You can link the server to an account again later.</p>
          </div>
        </Modal>
      )}
    </div>
  );
}
