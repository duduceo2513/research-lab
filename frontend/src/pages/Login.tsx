import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/Feedback'
import { Field } from '@/components/ui/Field'
import { Input } from '@/components/ui/Input'
import { useAuth } from '@/auth/context'

export function Login() {
  const { status, login, register } = useAuth()
  const location = useLocation()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from ?? '/'
    return <Navigate to={from} replace />
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(email, password)
      else await register({ email, password, first_name: firstName, last_name: lastName })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <p className="mb-3 text-[12px] font-medium uppercase tracking-wide text-ink-muted">
          Multi-agent research assistant for teachers
        </p>
        <h1 className="text-4xl font-extrabold leading-tight tracking-tight text-ink">
          Research <span className="text-accent">Lab</span>
        </h1>

        <form onSubmit={submit} className="mt-8 flex flex-col gap-4">
          {mode === 'register' ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="First name">
                <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} required autoComplete="given-name" />
              </Field>
              <Field label="Last name">
                <Input value={lastName} onChange={(e) => setLastName(e.target.value)} required autoComplete="family-name" />
              </Field>
            </div>
          ) : null}
          <Field label="E-mail">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" autoFocus />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </Field>
          {error ? <ErrorNotice error={error} /> : null}
          <Button type="submit" variant="primary" disabled={busy} className="w-full">
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>
        </form>

        <button
          type="button"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
          className="mt-4 text-[13px] text-ink-muted hover:text-accent"
        >
          {mode === 'login' ? 'No account? Register' : 'Already registered? Sign in'}
        </button>
      </div>
    </div>
  )
}
