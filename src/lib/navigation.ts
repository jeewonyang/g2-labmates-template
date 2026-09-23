/** One shortcut registry shared by the key handler and Sidebar labels. */
export const GOTO_SHORTCUTS: Record<string, string> = {
  h: "/today",
  t: "/today",
  i: "/inbox",
  p: "/projects",
  a: "/areas",
  x: "/archive",
  k: "/tasks",
  v: "/reviews",
  r: "/research",
  w: "/wiki",
  e: "/teams",
  s: "/settings",
};

export function shortcutFor(href: string): string | undefined {
  return Object.entries(GOTO_SHORTCUTS).find(([, destination]) => destination === href)?.[0];
}
