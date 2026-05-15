import type { NextAuthOptions } from "next-auth"
import GithubProvider from "next-auth/providers/github"

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
        token.githubId    = (profile as any)?.id
        token.login       = (profile as any)?.login
        token.avatarUrl   = (profile as any)?.avatar_url
      }
      return token
    },
    async session({ session, token }) {
      session.user.githubId  = token.githubId as number
      session.user.login     = token.login as string
      session.user.avatarUrl = token.avatarUrl as string
      session.accessToken    = token.accessToken as string
      return session
    },
  },
  pages: {
    signIn: "/login",
  },
}