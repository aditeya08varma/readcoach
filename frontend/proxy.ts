import { NextResponse } from "next/server";
import { auth } from "@/auth";

// Real, load-bearing detail (see docs/BUILD_LOG.md): Next.js 16 deprecated
// and renamed the `middleware.ts` file convention to `proxy.ts` (file name
// AND default export) - confirmed against this project's own installed
// Next.js docs (node_modules/next/dist/docs/.../file-conventions/proxy.md),
// not assumed from older training data, per frontend/AGENTS.md's own
// warning that this Next build differs from typical conventions. A file
// still named middleware.ts would not reliably protect anything.
// /admin/engineering is deliberately left unprotected - a technical/internal
// tool, not part of the per-user context problem this auth layer solves.
const PROTECTED_PATHS = ["/", "/read", "/dashboard", "/map"];

export default auth((req) => {
  const { pathname } = req.nextUrl;
  const isProtected = PROTECTED_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`)
  );
  if (isProtected && !req.auth) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }
});

export const config = {
  matcher: ["/", "/read/:path*", "/dashboard/:path*", "/map/:path*"],
};
