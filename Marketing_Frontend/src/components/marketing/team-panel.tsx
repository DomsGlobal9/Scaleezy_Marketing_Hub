/**
 * Team — the client's own people, with the permission matrix the server
 * actually enforces.
 *
 * Roles offered in the select are exactly `permissions.roles`; the matrix is
 * rendered from `permissions.capabilities`, never a hand-kept table. There is
 * no Invite button: the server says `can_invite: false` and why, and the
 * honest thing is to print its note rather than disable a control.
 */
import { Loader2, PauseCircle, PlayCircle, UserMinus, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ConfirmDialog,
  ErrorNote,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import { SectionTitle } from "@/components/marketing/primitives";
import {
  errorText,
  fetchTeam,
  formatAgo,
  reactivateTeamMember,
  removeTeamMember,
  setTeamRole,
  suspendTeamMember,
  type TeamData,
  type TeamMember,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export function TeamPanel() {
  const [team, setTeam] = useState<TeamData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTeam(await fetchTeam());
    } catch (e: unknown) {
      setError(errorText(e, "Could not load the team."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const ask = (request: ConfirmRequest) =>
    setConfirm({
      ...request,
      run: async (reason) => {
        await request.run(reason);
        await load();
      },
    });

  const changeRole = (member: TeamMember, role: string) => {
    if (role === member.role) return;
    ask({
      title: `Make ${member.username} ${role}?`,
      description:
        "The server re-checks that you may grant this role and that the client keeps an owner.",
      confirmLabel: "Change role",
      run: async () => {
        await setTeamRole(member.id, role);
        toast.success(`${member.username} is now ${role}.`);
      },
    });
  };

  const roles = team?.permissions.roles ?? [];

  return (
    <section className="surface-card mt-6 p-5 sm:p-6">
      <SectionTitle
        label="Team"
        title="Who works on this client"
        description="Roles are enforced by the server on every request; this table shows the same matrix it uses."
      />

      <ErrorNote message={error} />

      {loading && !team ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : team ? (
        <>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/50 text-[0.625rem] tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th className="px-3 py-2 font-semibold">Person</th>
                  <th className="px-3 py-2 font-semibold">Role</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Last active</th>
                  <th className="px-3 py-2 font-semibold">Added by</th>
                  <th className="px-3 py-2 font-semibold" />
                </tr>
              </thead>
              <tbody>
                {team.members.map((member) => (
                  <tr key={member.id} className="border-t border-border align-middle">
                    <td className="px-3 py-2">
                      <p className="font-medium text-foreground">
                        {member.full_name || member.username}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {member.username}
                        {member.email ? ` · ${member.email}` : ""}
                      </p>
                    </td>
                    <td className="px-3 py-2">
                      <Select
                        value={member.role}
                        onValueChange={(role) => changeRole(member, role)}
                      >
                        <SelectTrigger className="h-8 w-32 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {roles.map((r) => (
                            <SelectItem key={r.role} value={r.role}>
                              {r.role}
                            </SelectItem>
                          ))}
                          {!roles.some((r) => r.role === member.role) ? (
                            <SelectItem value={member.role}>{member.role}</SelectItem>
                          ) : null}
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill value={member.status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {formatAgo(member.last_active_at)}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {member.invited_by_username || "—"}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1.5">
                        {member.status === "ACTIVE" ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              ask({
                                title: `Suspend ${member.username}?`,
                                description:
                                  "They keep their seat but cannot act until reactivated.",
                                confirmLabel: "Suspend",
                                run: async () => {
                                  await suspendTeamMember(member.id);
                                  toast.success(`${member.username} suspended.`);
                                },
                              })
                            }
                          >
                            <PauseCircle className="size-3.5" /> Suspend
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              ask({
                                title: `Reactivate ${member.username}?`,
                                confirmLabel: "Reactivate",
                                run: async () => {
                                  await reactivateTeamMember(member.id);
                                  toast.success(`${member.username} reactivated.`);
                                },
                              })
                            }
                          >
                            <PlayCircle className="size-3.5" /> Reactivate
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive hover:text-destructive"
                          onClick={() =>
                            ask({
                              title: `Remove ${member.username} from this client?`,
                              description:
                                "They lose access to this client. Their account and other clients are untouched.",
                              confirmLabel: "Remove",
                              destructive: true,
                              run: async () => {
                                await removeTeamMember(member.id);
                                toast.success(`${member.username} removed.`);
                              },
                            })
                          }
                        >
                          <UserMinus className="size-3.5" /> Remove
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {team.members.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-3 py-6 text-center text-sm text-muted-foreground">
                      No members were returned.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <p className="mt-3 flex items-start gap-2 rounded-lg border border-gold/30 bg-gold/8 px-3 py-2 text-xs text-foreground">
            <Users className="mt-0.5 size-3.5 shrink-0 text-gold" />
            <span>{team.invite_note}</span>
          </p>

          <h3 className="mt-6 text-sm font-semibold tracking-tight text-foreground">
            Permission matrix
          </h3>
          <p className="mb-2 text-xs text-muted-foreground">
            Derived from the server's role ranking. A role grants everything at its rank and below.
          </p>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/50 text-[0.625rem] tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th className="px-3 py-2 font-semibold">Capability</th>
                  {roles.map((r) => (
                    <th key={r.role} className="px-3 py-2 text-center font-semibold">
                      {r.role}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {team.permissions.capabilities.map((cap) => (
                  <tr key={cap.key} className="border-t border-border">
                    <td className="px-3 py-1.5">
                      <p className="text-foreground">{cap.label}</p>
                      <p className="text-[0.625rem] text-muted-foreground">
                        from {cap.minimum_role}
                      </p>
                    </td>
                    {roles.map((r) => (
                      <td key={r.role} className="px-3 py-1.5 text-center">
                        <span
                          className={cn(
                            "inline-block size-2.5 rounded-full",
                            cap.granted_to.includes(r.role) ? "bg-emerald-500" : "bg-border",
                          )}
                          aria-label={cap.granted_to.includes(r.role) ? "granted" : "not granted"}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {loading && team ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Refreshing…
        </p>
      ) : null}

      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}
