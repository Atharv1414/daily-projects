import { useEffect } from 'react'

export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · Kestrel & Lock` : 'Kestrel & Lock · Narrowboat holidays from Marrowby Wharf'
  }, [title])
}
