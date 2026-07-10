import type { NextAuthOptions } from "next-auth"
import GithubProvider from "next-auth/providers/github"
import type { JWT } from "next-auth/jwt"

const GITHUB_TOKEN_URL  = "https://github.com/login/oauth/access_token"

/*
 * Exchange the stored refresh token for a new access token.
 *
 * Only works if the GitHub OAuth App has "expiring user tokens" enabled —
 * that's what makes GitHub issue a refresh_token in the first place. If it
 * isn't enabled, token.refreshToken will never be set and we skip this
 * entirely (see the jwt callback below).
 */

async function refreshAccessToken(token: JWT) : Promise<JWT> {
  try {

    const response = await fetch(GITHUB_TOKEN_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json"
      },
      body: new URLSearchParams({
        client_id: process.env.GITHUB_OAUTH_CLIENT_ID!,
        client_secret: process.env.GITHUB_OAUTH_CLIENT_SECRET!,
        grant_type: "refresh_token",
        refresh_token: token.refreshToken as string
      })
    })

    const refreshed = await response.json()

    if (!response.ok || refreshed.error) {
      throw refreshed
    }

    return {
      ...token,
      accessToken: refreshed.access_token,
      accessTokenExpires: Date.now() + refreshed.expires_in * 1000,
      //GitHub rotates the refresh token on each use
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      error: undefined,
    }
  }
  catch(err) {
    console.error("Error refreshing GitHub access token", err)
    return {
      ...token,
      error: "RefreshAccessTokenError"
    }
  }
}


export const authOptions: NextAuthOptions = {
  providers: [
    GithubProvider({
      clientId: process.env.GITHUB_OAUTH_CLIENT_ID!,
      clientSecret: process.env.GITHUB_OAUTH_CLIENT_SECRET!,
      authorization: { params: { scope: "read:user repo" } },
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken = account.access_token
        token.refreshToken = account.refresh_token
        token.accessTokenExpires = account.expires_at
          ? account.expires_at * 1000
          : undefined
        token.githubId    = (profile as any)?.id
        token.login       = (profile as any)?.login
        token.avatarUrl   = (profile as any)?.avatar_url
        
        return token
      }
      // No expiry recorded — expiring tokens aren't enabled on the App,
      // so the token is long-lived. Same behavior as before this change.
      if (!token.accessTokenExpires) {
        return token
      }
 
      // Still valid — refresh 60s early so requests never race an
      // about-to-expire token.
      if (Date.now() < token.accessTokenExpires - 60_000) {
        return token
      }
 
      // Expired: get a new one.
      return refreshAccessToken(token)

    },
    
    async session({ session, token }) {
      session.user.githubId  = token.githubId as number
      session.user.login     = token.login as string
      session.user.avatarUrl = token.avatarUrl as string
      session.accessToken    = token.accessToken as string
      session.error = token.error as string | undefined
      return session
    },
  },
  pages: {
    signIn: "/login",
  },
}