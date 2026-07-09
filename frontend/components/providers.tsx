"use client"

import { useEffect } from "react"
import { SessionProvider, useSession, signIn } from "next-auth/react"

function AuthErrorHandler({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession()

  useEffect(() => {
    // Set by lib/auth.ts's jwt callback when the GitHub refresh-token
    // exchange fails (refresh token itself expired/revoked, or expiring
    // tokens aren't enabled on the OAuth App so there's nothing to refresh).
    // Re-running signIn() sends the user through GitHub's OAuth flow again
    // — this is what replaces the old "blank dashboard, no error" behavior.
    if (session?.error === "RefreshAccessTokenError") {
      signIn("github")
    }
  }, [session])

  return <>{children}</>
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AuthErrorHandler>{children}</AuthErrorHandler>
    </SessionProvider>
  )
}