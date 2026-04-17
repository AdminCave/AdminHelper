export function parseTags(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(',')
    .map((t) => t.trim().slice(0, 50))
    .filter((t) => {
      if (!t || seen.has(t)) return false;
      seen.add(t);
      return true;
    });
}

export function extractAllTags<T extends { tags?: string[] }>(items: T[]): string[] {
  return Array.from(new Set(items.flatMap((i) => i.tags ?? []))).sort();
}
