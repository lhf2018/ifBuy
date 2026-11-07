import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type Account } from './api'

type Ctx = {
  accounts: Account[]
  accountId: number | null
  account: Account | null
  ready: boolean
  setAccountId: (id: number) => void
  refreshAccounts: () => Promise<void>
}

const AccountContext = createContext<Ctx | null>(null)

export function AccountProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [ready, setReady] = useState(false)
  const [accountId, setAccountIdState] = useState<number | null>(() => {
    const raw = localStorage.getItem('ifbuy_account_id')
    return raw ? Number(raw) : null
  })
  const alive = useRef(true)

  const refreshAccounts = useCallback(async () => {
    const list = await api.listAccounts()
    if (!alive.current) return
    setAccounts(list)
    setAccountIdState((prev) => {
      if (!list.length) return null
      if (prev && list.some((a) => a.id === prev)) return prev
      const next = list[0].id
      localStorage.setItem('ifbuy_account_id', String(next))
      return next
    })
    setReady(true)
  }, [])

  useEffect(() => {
    alive.current = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const boot = async (attempt = 0) => {
      try {
        await refreshAccounts()
      } catch (e) {
        console.error(e)
        if (!alive.current) return
        if (attempt < 8) {
          timer = setTimeout(() => boot(attempt + 1), 400 * (attempt + 1))
        } else {
          setReady(true)
        }
      }
    }
    boot()

    const onFocus = () => {
      refreshAccounts().catch(() => {})
    }
    window.addEventListener('focus', onFocus)
    return () => {
      alive.current = false
      if (timer) clearTimeout(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [refreshAccounts])

  const setAccountId = (id: number) => {
    setAccountIdState(id)
    localStorage.setItem('ifbuy_account_id', String(id))
  }

  const account = useMemo(() => accounts.find((a) => a.id === accountId) || null, [accounts, accountId])

  return (
    <AccountContext.Provider value={{ accounts, accountId, account, ready, setAccountId, refreshAccounts }}>
      {children}
    </AccountContext.Provider>
  )
}

export function useAccount() {
  const ctx = useContext(AccountContext)
  if (!ctx) throw new Error('AccountProvider missing')
  return ctx
}
