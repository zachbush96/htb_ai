import React from 'react'
import { cleanDisplayText, findCredentialHints } from '../lib/app-utils'
import { EmptyState, Panel } from '../components/primitives'
import { SupportCard, SupportModal, SupportNotice, SupportWhy, useSupportActions } from './support-actions'

function credentialSourceEntries(activeTarget) {
  return [
    ...((activeTarget?.observations || []).map((item) => ({
      kind: 'observation',
      label: item.title || 'Observation',
      raw: cleanDisplayText(`${item.title || ''}\n${item.summary || ''}`, ''),
    }))),
    ...((activeTarget?.agent_actions || []).map((item) => ({
      kind: 'action',
      label: item.label || 'Action output',
      raw: cleanDisplayText(`${item.label || ''}\n${item.summary || ''}\n${item.result_excerpt || ''}`, ''),
    }))),
  ].filter((item) => item.raw)
}

function credentialWhy(hint, source) {
  const matchType = /token|api[_-]?key|secret/i.test(hint)
    ? 'secret-shaped value'
    : /pass|pwd/i.test(hint)
      ? 'password-shaped value'
      : 'login-style identifier'

  return [
    `This hint was surfaced because the parser matched a ${matchType} pattern inside stored evidence.`,
    source ? `The current match came from the ${source.kind} named "${source.label}".` : 'No single evidence row could be isolated for this hint, so only the normalized hint text is available.',
    'Use the raw source action when you need surrounding context before trusting or reusing the value.',
  ].join(' ')
}

export function CredentialsView({ activeTarget }) {
  const hints = findCredentialHints(activeTarget)
  const sources = credentialSourceEntries(activeTarget)
  const { notice, modal, closeModal, copyValue, openText, openJson } = useSupportActions()

  const panelActions = [
    {
      id: 'copy-all-hints',
      label: 'Copy all hints',
      description: 'Copy every parsed hint as newline-delimited text.',
      disabled: !hints.length,
      onSelect: () => copyValue('Credential hints', hints.join('\n')),
    },
    {
      id: 'view-raw-context',
      label: 'View raw credential context',
      description: 'Inspect the normalized observation and action excerpts behind these hints.',
      disabled: !sources.length,
      onSelect: () => openJson('Credential source context', { hints, sources }, {
        description: 'This is the exact normalized material scanned for username, password, token, and secret patterns.',
      }),
    },
  ]

  return (
    <div className="view-grid">
      <Panel title="Credential Hints" meta={hints.length} className="wide" actions={<SupportNotice notice={notice} />}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.8rem' }}>
          <div style={{ minWidth: '16rem' }}>
            <SupportCard
              title="Credential actions"
              subtitle="Quick utilities for the parsed hint set."
              menuItems={panelActions}
            />
          </div>
        </div>
        <div className="credential-list">
          {hints.map((hint, index) => {
            const source = sources.find((item) => item.raw.includes(hint))
            return (
              <SupportCard
                key={`${hint}-${index}`}
                meta={source ? source.kind : 'parsed hint'}
                title={hint}
                subtitle={source ? source.label : 'No matching evidence row was preserved for this exact value.'}
                menuItems={[
                  {
                    id: `copy-hint-${index}`,
                    label: 'Copy hint',
                    description: 'Copy this hint exactly as displayed.',
                    onSelect: () => copyValue('Credential hint', hint),
                  },
                  {
                    id: `raw-hint-${index}`,
                    label: 'View raw source',
                    description: 'Show the normalized observation or action text that produced the hint.',
                    disabled: !source,
                    onSelect: () => openText(`Raw source for hint ${index + 1}`, source?.raw || '', {
                      description: source ? `${source.kind} :: ${source.label}` : 'No raw source is available for this parsed hint.',
                    }),
                  },
                ]}
              >
                <code>{hint}</code>
                <SupportWhy title="Ask why" body={credentialWhy(hint, source)} />
              </SupportCard>
            )
          })}
          {!hints.length ? <EmptyState title="No credential material" body="No usernames, passwords, tokens, or keys have been parsed from current evidence." /> : null}
        </div>
        <SupportModal modal={modal} onClose={closeModal} />
      </Panel>
    </div>
  )
}
