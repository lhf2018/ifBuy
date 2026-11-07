import { QueryClient, dehydrate, hydrate, type DehydratedState } from '@tanstack/react-query'

const STORAGE_KEY = 'ifbuy-query-cache-v1'
const PERSIST_MS = 30 * 60 * 1000 // keep browser cache up to 30 min

function loadPersisted(): DehydratedState | undefined {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return undefined
    const parsed = JSON.parse(raw) as { savedAt: number; state: DehydratedState }
    if (!parsed?.state || !parsed.savedAt) return undefined
    if (Date.now() - parsed.savedAt > PERSIST_MS) {
      sessionStorage.removeItem(STORAGE_KEY)
      return undefined
    }
    return parsed.state
  } catch {
    return undefined
  }
}

function persist(client: QueryClient) {
  try {
    const state = dehydrate(client, {
      shouldDehydrateQuery: (q) => q.state.status === 'success',
    })
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ savedAt: Date.now(), state }))
  } catch {
    // quota / private mode — ignore
  }
}

export function createAppQueryClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 60_000,
        gcTime: 30 * 60_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        // Refresh: show cached first; refetch in background only if stale
        refetchOnMount: true,
      },
    },
  })

  const saved = loadPersisted()
  if (saved) {
    hydrate(client, saved)
  }

  let timer: ReturnType<typeof setTimeout> | undefined
  const schedulePersist = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => persist(client), 400)
  }
  client.getQueryCache().subscribe(schedulePersist)
  client.getMutationCache().subscribe(schedulePersist)

  return client
}
