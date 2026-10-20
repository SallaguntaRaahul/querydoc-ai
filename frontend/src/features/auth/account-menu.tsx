import { Loader2, LogOut, Trash2, UserRound } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useDeleteAccount, useLogout, useMe } from '@/services/queries'

/** Signed-in account with sign-out and account deletion. Hidden in local single-user mode. */
export function AccountMenu({ collapsed }: { collapsed: boolean }) {
  const { data: me } = useMe(false)
  const logout = useLogout()
  const remove = useDeleteAccount()
  const navigate = useNavigate()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [password, setPassword] = useState('')

  if (!me?.auth_enabled) return null

  const signOut = async () => {
    await logout.mutateAsync().catch(() => undefined)
    navigate('/login', { replace: true })
  }
  const deleteAccount = async () => {
    try {
      await remove.mutateAsync(password)
      toast.success('Your account and all its documents were deleted.')
      navigate('/signup', { replace: true })
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Could not delete the account')
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" aria-label="Account"
            className={cn('w-full justify-start gap-2 px-2 text-xs font-normal text-muted-foreground', collapsed && 'size-9 justify-center p-0')}>
            <UserRound className="size-4 shrink-0" aria-hidden />
            {!collapsed && <span className="truncate">{me.email}</span>}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-60">
          <DropdownMenuLabel className="truncate font-normal text-muted-foreground">{me.email}{me.is_admin ? ' · admin' : ''}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={signOut}><LogOut className="size-4" /> Sign out</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setConfirmOpen(true)} className="text-destructive focus:text-destructive">
            <Trash2 className="size-4" /> Delete account…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={confirmOpen} onOpenChange={(o) => { setConfirmOpen(o); if (!o) setPassword('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete your account?</DialogTitle>
            <DialogDescription>This permanently deletes your account, every uploaded PDF, its index entries and all conversations. It cannot be undone.</DialogDescription>
          </DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); void deleteAccount() }} className="grid gap-1.5">
            <Label htmlFor="confirm-password">Confirm with your password</Label>
            <Input id="confirm-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <DialogFooter className="mt-4">
              <Button type="button" variant="ghost" onClick={() => setConfirmOpen(false)}>Cancel</Button>
              <Button type="submit" variant="destructive" disabled={!password || remove.isPending}>
                {remove.isPending && <Loader2 className="size-4 animate-spin" />} Delete everything
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
