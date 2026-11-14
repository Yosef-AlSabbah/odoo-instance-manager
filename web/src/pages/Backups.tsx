import { Archive, Download, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { useBackups, useCall } from "@/api/queries";
import { Page, PageHead } from "@/components/Shell";
import { Button, Empty, Skeleton, Tag } from "@/components/ui/basics";
import { useToast } from "@/components/ui/overlay";
import { ago, bytes, dateTime } from "@/lib/format";

const KIND: Record<string, string> = { manual: "By hand", daily: "Daily", deletion: "Before deletion", "before-restore": "Before a restore", "before-rollback": "Before a rollback", "before-repair": "Before a repair" };

export function BackupsPage() {
  const { data: backups, isPending } = useBackups();
  const toast = useToast();
  const remove = useCall((file: string) => api.del(`/backups/${encodeURIComponent(file)}`), [["backups"]]);
  const total = backups?.reduce((sum, b) => sum + b.size, 0) ?? 0;
  return (
    <Page>
      <PageHead title="Backups">
        Odoo-format zips (database and files): daily ones for each instance used that day, ones taken by hand, and one before every deletion. Restore one from an instance's page, into that instance or another one of the same Odoo version, or start a new instance from it. {backups?.length ? `${backups.length} backups · ${bytes(total)}` : ""}
      </PageHead>
      <div className="card rise">
        {isPending ? <div className="card-body"><Skeleton height={140} /></div> : !backups?.length ? (
          <Empty icon={<Archive />} title="No backups yet">An instance is backed up before it is deleted, or with Back up now on its page.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Instance</th><th>Database</th><th>Odoo</th><th>Kind</th><th>Taken</th><th>Size</th><th /></tr></thead>
              <tbody>
                {backups.map((b) => (
                  <tr key={b.file}>
                    <td>{b.instance}</td>
                    <td className="mono small">{b.db}</td>
                    <td className="mono small">{b.series ?? <span className="faint">?</span>}{b.edition === "enterprise" ? " Enterprise" : ""}</td>
                    <td><Tag tone={b.kind === "daily" ? "accent" : undefined}>{KIND[b.kind] ?? b.kind}</Tag></td>
                    <td className="small">{dateTime(b.created)} <span className="faint">· {ago(b.created)}</span></td>
                    <td className="small tabular">{bytes(b.size)}</td>
                    <td className="actions">
                      <a className="btn sm soft" href={`/api/v1/backups/${encodeURIComponent(b.file)}`} download><Download /> Download</a>{" "}
                      <Button size="sm" variant="ghost" icon={<Trash2 />} aria-label="Delete" onClick={() => confirm(`Delete ${b.file}? This cannot be undone.`) && remove.mutate(b.file, { onSuccess: () => toast("success", "Backup deleted") })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Page>
  );
}
