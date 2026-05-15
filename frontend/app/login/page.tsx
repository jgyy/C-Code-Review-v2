"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function LoginContent() {
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") ?? "/";

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="w-full max-w-sm px-8 py-10 bg-gray-900 border border-gray-800 rounded-2xl shadow-xl flex flex-col items-center gap-6">
        {/* Logo / wordmark */}
        <div className="flex flex-col items-center gap-1 mb-2">
          <span className="text-2xl font-bold tracking-tight text-white">
            C Code Diff Reviewer
          </span>
          <span className="text-sm text-gray-400">Sign in to continue</span>
        </div>

        {/* GitHub OAuth button */}
        <button
          onClick={() => signIn("github", { callbackUrl })}
          className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-white text-gray-900 font-semibold rounded-lg hover:bg-gray-100 active:bg-gray-200 transition-colors duration-150 shadow-sm"
        >
          {/* GitHub icon */}
          <svg
            className="w-5 h-5 shrink-0"
            viewBox="0 0 24 24"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M12 0C5.373 0 0 5.373 0 12c0 5.303 3.438 9.8 8.205 11.387.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.09-.745.083-.73.083-.73 1.205.085 1.84 1.237 1.84 1.237 1.07 1.834 2.807 1.304 3.492.997.108-.775.418-1.305.762-1.605-2.665-.3-5.467-1.332-5.467-5.93 0-1.31.468-2.381 1.236-3.221-.124-.303-.536-1.524.117-3.176 0 0 1.008-.322 3.3 1.23A11.51 11.51 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.29-1.552 3.297-1.23 3.297-1.23.655 1.652.243 2.873.12 3.176.77.84 1.235 1.911 1.235 3.221 0 4.61-2.807 5.625-5.479 5.92.43.372.823 1.102.823 2.222 0 1.606-.015 2.898-.015 3.293 0 .322.216.694.825.576C20.565 21.796 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
          </svg>
          Continue with GitHub
        </button>

        <p className="text-xs text-gray-500 text-center">
          By signing in you agree to our{" "}
          <a href="/terms" className="underline hover:text-gray-300">
            Terms
          </a>{" "}
          and{" "}
          <a href="/privacy" className="underline hover:text-gray-300">
            Privacy Policy
          </a>
          .
        </p>
      </div>
    </main>
  );
}

// useSearchParams must be wrapped in Suspense
export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}
