import { useId } from 'react'

export default function Field({ label, hint, error, value, onChange, prefix, ...input }) {
  const id = useId()
  const described = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return (
    <div className={error ? 'field field--wrong' : 'field'}>
      <label htmlFor={id}>{label}</label>
      {hint && <p className="field__hint" id={`${id}-hint`}>{hint}</p>}
      <div className="field__box">
        {prefix && <span aria-hidden="true">{prefix}</span>}
        <input id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={described} aria-invalid={error ? true : undefined} {...input} />
      </div>
      {error && <p className="field__error" id={`${id}-error`}>{error}</p>}
    </div>
  )
}

/** Lists what is wrong at the top of a form and takes focus, so nobody has to hunt for it. */
export function ErrorSummary({ errors, boxRef }) {
  const list = Object.values(errors)
  return (
    <div ref={boxRef} tabIndex={-1} className="summary" role="alert" hidden={list.length === 0}>
      {list.length > 0 && <>
        <p><b>{list.length === 1 ? 'One thing to fix' : `${list.length} things to fix`}</b></p>
        <ul>{list.map((e) => <li key={e}>{e}</li>)}</ul>
      </>}
    </div>
  )
}
