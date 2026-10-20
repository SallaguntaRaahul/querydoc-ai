import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { z } from 'zod'

import { Logo } from '@/components/common'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import { useAuthAction, useAuthConfig, useMe } from '@/services/queries'

const schema = z.object({
  email: z.string().trim().email('Enter a valid email address'),
  password: z.string().min(8, 'Use at least 8 characters').max(128, 'Use at most 128 characters'),
})
type Form = z.infer<typeof schema>

/** Only same-app paths are honoured as redirect targets. */
function safeNext(raw: string | null) {
  return raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
}

export default function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const config = useAuthConfig()
  const me = useMe(config.data?.auth_enabled ?? false)
  const action = useAuthAction(mode)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema), mode: 'onTouched' })

  if (config.data && !config.data.auth_enabled) return <Navigate to="/" replace />
  if (me.data) return <Navigate to={next} replace />

  const isSignup = mode === 'signup'
  const signupClosed = isSignup && config.data?.signup_enabled === false
  const onSubmit = async (values: Form) => {
    try {
      await action.mutateAsync(values)
      navigate(next, { replace: true })
    } catch {
      /* shown below */
    }
  }
  const error = action.error instanceof ApiError ? action.error.message : action.error ? 'Something went wrong. Try again.' : null
  const other = isSignup ? '/login' : '/signup'
  const otherHref = next !== '/' ? `${other}?next=${encodeURIComponent(next)}` : other

  return (
    <main className="grid min-h-dvh place-items-center bg-background px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center"><Logo /></div>
        <Card>
          <CardHeader>
            <CardTitle className="text-xl"><h1>{isSignup ? 'Create your account' : 'Sign in'}</h1></CardTitle>
            <CardDescription>
              {isSignup
                ? 'Your PDFs and conversations are private to your account.'
                : 'Ask questions about your PDFs and get answers with page citations.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {signupClosed ? (
              <Alert><AlertDescription>New sign-ups are currently closed.</AlertDescription></Alert>
            ) : (
              <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate aria-label={isSignup ? 'Sign up' : 'Sign in'}>
                <div className="grid gap-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input id="email" type="email" autoComplete="email" autoFocus aria-invalid={!!formState.errors.email} {...register('email')} />
                  {formState.errors.email && <p role="alert" className="text-xs text-destructive">{formState.errors.email.message}</p>}
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="password">Password</Label>
                  <Input id="password" type="password" autoComplete={isSignup ? 'new-password' : 'current-password'}
                    aria-invalid={!!formState.errors.password} {...register('password')} />
                  {formState.errors.password
                    ? <p role="alert" className="text-xs text-destructive">{formState.errors.password.message}</p>
                    : isSignup && <p className="text-xs text-muted-foreground">At least 8 characters. There is no password reset, so keep it safe.</p>}
                </div>
                {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
                <Button type="submit" disabled={action.isPending} className="w-full">
                  {action.isPending && <Loader2 className="size-4 animate-spin" />}
                  {isSignup ? 'Create account' : 'Sign in'}
                </Button>
              </form>
            )}
            <p className="mt-4 text-center text-sm text-muted-foreground">
              {isSignup ? 'Already have an account? ' : 'New here? '}
              <Link to={otherHref} className="font-medium text-primary underline-offset-4 hover:underline">
                {isSignup ? 'Sign in' : 'Create an account'}
              </Link>
            </p>
          </CardContent>
        </Card>
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Built by Raahul Sallagunta ·{' '}
          <a href="https://github.com/SallaguntaRaahul/querydoc-ai" target="_blank" rel="noreferrer" className="underline underline-offset-4">Source code</a>
        </p>
      </div>
    </main>
  )
}
