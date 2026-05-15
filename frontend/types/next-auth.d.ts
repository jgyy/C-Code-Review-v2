import "next-auth"
import "next-auth/jwt"

declare module "next-auth" {
  interface Session {
    accessToken?: string
    user: {
      githubId?: number
      login?: string
      avatarUrl?: string
    } & DefaultSession["user"]
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string
    githubId?: number
    login?: string
    avatarUrl?: string
  }
}