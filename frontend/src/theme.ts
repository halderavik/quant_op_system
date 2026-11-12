/** Theme preference: "system" follows the OS, the others force a mode. */

import { useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";

const KEY = "sras.theme";

export function resolveTheme(preference: ThemePreference, systemDark: boolean): "light" | "dark" {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

export function nextPreference(preference: ThemePreference): ThemePreference {
  if (preference === "system") return "light";
  if (preference === "light") return "dark";
  return "system";
}

function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Storage can be blocked; fall back to the system setting.
  }
  return "system";
}

export function useTheme(): [ThemePreference, (next: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = resolveTheme(preference, media.matches);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preference]);

  function update(next: ThemePreference) {
    setPreference(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Ignore: the choice still applies for this session.
    }
  }

  return [preference, update];
}
