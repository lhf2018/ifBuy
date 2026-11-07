import { useEffect, useId, useRef, useState } from 'react'
import type { Account } from '../api'

const NAME_KEY = 'ifbuy_account_name'

export function AccountSelect({
  accounts,
  value,
  onChange,
  loading = false,
}: {
  accounts: Account[]
  value: number | null
  onChange: (id: number) => void
  loading?: boolean
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const listId = useId()
  const current = accounts.find((a) => a.id === value) || accounts[0]
  const cachedName = typeof localStorage !== 'undefined' ? localStorage.getItem(NAME_KEY) : null
  const displayName = current?.name || cachedName || '加载中…'
  const ready = !loading && !!current

  useEffect(() => {
    if (current?.name) localStorage.setItem(NAME_KEY, current.name)
  }, [current?.name])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className={`account-select ${open ? 'open' : ''} ${ready ? '' : 'is-loading'}`} ref={rootRef}>
      <button
        type="button"
        className="account-select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-busy={!ready}
        disabled={!ready}
        onClick={() => ready && setOpen((v) => !v)}
      >
        <span className="account-select-label">当前账本</span>
        <span className={`account-select-value ${ready ? '' : 'is-skeleton'}`}>{displayName}</span>
        <span className="account-select-caret" aria-hidden>
          ▾
        </span>
      </button>
      {open && ready && (
        <ul className="account-select-menu" id={listId} role="listbox">
          {accounts.map((a) => (
            <li key={a.id} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={a.id === current.id}
                className={`account-select-option ${a.id === current.id ? 'active' : ''}`}
                onClick={() => {
                  onChange(a.id)
                  localStorage.setItem(NAME_KEY, a.name)
                  setOpen(false)
                }}
              >
                {a.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
