import type { ReactNode } from 'react'
import { FileText } from 'lucide-react'
import './fixed-policy.css'

export default function DocumentCard({ title, description, status, confirmed = false, sample = false, actions, children }: {
  title: string; description: string; status: string; confirmed?: boolean; sample?: boolean
  actions?: ReactNode; children?: ReactNode
}) {
  return <div className="claim-document-card">
    <div className="claim-document-header">
      <FileText size={18} aria-hidden="true"/>
      <div className="claim-document-name">
        {sample ? <strong>{title}</strong> : <h3>{title}</h3>}
        <p>{description}</p>
      </div>
      <span className={`status ${confirmed ? 'status-green' : 'status-amber'}`}>{status}</span>
    </div>
    {children}
    {actions && <div className="claim-document-actions">{actions}</div>}
  </div>
}
