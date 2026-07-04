"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";

// @clerk/nextjs v7 dropped the <SignedIn>/<SignedOut> wrapper components in
// favor of a lower-level <Show> primitive with an undocumented prop shape at
// the time this was written -- useAuth()'s isLoaded/isSignedIn flags are the
// stable, well-documented way to branch on auth state, so that's used here
// and in app/page.tsx instead of guessing at <Show>'s API.
export function AuthHeaderControls() {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) return null;
  return isSignedIn ? <UserButton /> : <SignInButton />;
}
