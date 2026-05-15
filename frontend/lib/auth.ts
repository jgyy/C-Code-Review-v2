import NextAuth from "next-auth"
import GitHub from "next-auth/providers/github"

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    GitHub({
      clientId: process.env.GITHUB_OAUTH_CLIENT_ID!,
      clientSecret: process.env.GITHUB_OAUTH_CLIENT_SECRET!,
      // Request repo scope so we can pass the token to the backend
      authorization: { params: { scope: "read:user repo" } },
    }),
  ],
  callbacks: {
    // Persist the GitHub access token and user info into the JWT
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken  = account.access_token
        token.githubId     = (profile as any).id
        token.login        = (profile as any).login
        token.avatarUrl    = (profile as any).avatar_url
      }
      return token
    },
    // Expose what the client can see via useSession()
    async session({ session, token }) {
      session.user.githubId   = token.githubId as number
      session.user.login      = token.login as string
      session.user.avatarUrl  = token.avatarUrl as string
      session.accessToken     = token.accessToken as string
      return session
    },
  },
  pages: {
    signIn: "/login",
  },
})
