import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { axe } from 'vitest-axe'

import { makeQueryClient, Providers } from '@/app/providers'
import { AuthGate } from '@/features/auth/auth-gate'
import AuthPage from '@/pages/auth-page'
import SettingsPage from '@/pages/settings-page'
import { mockFetch, renderWithProviders, sampleSettings } from '@/test/utils'

const user = { id: 'u1', email: 'alice@example.com', is_admin: false, auth_enabled: true }
const notSignedIn = () => new Response(JSON.stringify({ error: { code: 'not_authenticated', message: 'Sign in to continue.' } }), { status: 401 })

function renderApp(initial: string) {
  const client = makeQueryClient()
  client.setDefaultOptions({ queries: { retry: false } })
  const router = createMemoryRouter([
    { path: '/login', element: <AuthPage mode="login" /> },
    { path: '/signup', element: <AuthPage mode="signup" /> },
    { path: '*', element: <AuthGate><div>Private app</div></AuthGate> },
  ], { initialEntries: [initial] })
  render(<Providers client={client}><RouterProvider router={router} /></Providers>)
  return router
}

describe('Accounts', () => {
  it('sends signed-out visitors to sign-in, then back to where they were going', async () => {
    let signedIn = false
    const { calls } = mockFetch({
      '/auth/config': () => ({ auth_enabled: true, signup_enabled: true }),
      '/auth/me': () => (signedIn ? user : notSignedIn()),
      'POST /auth/login': () => { signedIn = true; return user },
    })
    const router = renderApp('/library')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.search).toBe('?next=%2Flibrary')

    await userEvent.type(screen.getByLabelText('Email'), 'not-an-email')
    await userEvent.type(screen.getByLabelText('Password'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(calls.some((c) => c.url.endsWith('/auth/login'))).toBe(false)

    await userEvent.clear(screen.getByLabelText('Email'))
    await userEvent.type(screen.getByLabelText('Email'), 'alice@example.com')
    await userEvent.clear(screen.getByLabelText('Password'))
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Private app')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/library')
    const login = calls.find((c) => c.url.endsWith('/auth/login'))!
    expect(JSON.parse(String(login.init?.body))).toEqual({ email: 'alice@example.com', password: 'correct horse' })
  })

  it('shows the server error for wrong credentials and has no a11y violations', async () => {
    mockFetch({
      '/auth/config': () => ({ auth_enabled: true, signup_enabled: true }),
      '/auth/me': notSignedIn,
      'POST /auth/signup': () => new Response(JSON.stringify({ error: { code: 'email_taken', message: 'An account with this email already exists. Sign in instead.' } }), { status: 409 }),
    })
    renderApp('/signup')
    expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Email'), 'alice@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText(/already exists/)).toBeInTheDocument()
    expect(await axe(document.body)).toHaveNoViolations()
  })

  it('local single-user mode skips sign-in entirely', async () => {
    const { calls } = mockFetch({ '/auth/config': () => ({ auth_enabled: false, signup_enabled: true }) })
    renderApp('/')
    expect(await screen.findByText('Private app')).toBeInTheDocument()
    expect(calls.some((c) => c.url.endsWith('/auth/me'))).toBe(false)
  })

  it('ignores off-site redirect targets after sign-in', async () => {
    mockFetch({
      '/auth/config': () => ({ auth_enabled: true, signup_enabled: true }),
      '/auth/me': () => user,
    })
    const router = renderApp('/login?next=//evil.example/phish')
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })

  it('settings are read-only for non-admin accounts', async () => {
    mockFetch({
      '/settings': () => ({ ...sampleSettings, options: { ...sampleSettings.options, can_edit: false } }),
      '/auth/config': () => ({ auth_enabled: true, signup_enabled: true }),
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByTestId('settings-read-only')).toBeInTheDocument()
    expect(screen.queryByTestId('save-settings')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Chunk size (characters)')).toBeDisabled()
  })
})
