import { useQueryState } from 'nuqs'
import { SessionEntry } from '@/types/os'
import { Button } from '../../../ui/button'
import useSessionLoader from '@/hooks/useSessionLoader'
import { deleteSessionAPI } from '@/api/os'
import { useTurboRefiSession } from '@/hooks/useTurboRefiSession'
import { useStore } from '@/store'
import { toast } from 'sonner'
import Icon from '@/components/ui/icon'
import { useState } from 'react'
import DeleteSessionModal from './DeleteSessionModal'
import useChatActions from '@/hooks/useChatActions'
import { isTurboRefiLoanOfficer } from '@/lib/turborefi'
import { truncateText, cn } from '@/lib/utils'

type SessionItemProps = SessionEntry & {
  isSelected: boolean
  currentSessionId: string | null
  onSessionClick: () => void
}
const SessionItem = ({
  session_name: title,
  session_id,
  isSelected,
  currentSessionId,
  onSessionClick
}: SessionItemProps) => {
  const [agentId] = useQueryState('agent')
  const [teamId] = useQueryState('team')
  const [dbId] = useQueryState('db_id')
  const [, setSessionId] = useQueryState('session')
  const [, setTurboRefiSessionId] = useQueryState('refi_session')
  const authToken = useStore((state) => state.authToken)
  const { getSession } = useSessionLoader()
  const { loadSession, deleteSession: deleteTurboRefiSession } =
    useTurboRefiSession()
  const { selectedEndpoint, sessionsData, setSessionsData, mode, agents } =
    useStore()
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const { clearChat } = useChatActions()
  const selectedAgent = agents.find((agent) => agent.id === agentId)
  const isTurboRefiSelected =
    mode === 'agent' && isTurboRefiLoanOfficer(selectedAgent?.name)

  const handleGetSession = async () => {
    try {
      if (isTurboRefiSelected) {
        onSessionClick()
        await loadSession(session_id)
        setTurboRefiSessionId(session_id)
        setSessionId(null)
        return
      }
      if (!(agentId || teamId || dbId)) return

      onSessionClick()
      await getSession(
        {
          entityType: mode,
          agentId,
          teamId,
          dbId: dbId ?? ''
        },
        session_id
      )
      setSessionId(session_id)
    } catch (error) {
      toast.error(
        `Failed to load session: ${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  const handleDeleteSession = async () => {
    setIsDeleting(true)
    try {
      if (isTurboRefiSelected) {
        await deleteTurboRefiSession(session_id)
        if (sessionsData) {
          setSessionsData(sessionsData.filter((s) => s.session_id !== session_id))
        }
        if (currentSessionId === session_id) {
          setTurboRefiSessionId(null)
          clearChat()
        }
        toast.success('Session deleted')
        return
      }

      if (!(agentId || teamId || dbId)) return
      const response = await deleteSessionAPI(
        selectedEndpoint,
        dbId ?? '',
        session_id,
        authToken
      )

      if (response?.ok && sessionsData) {
        setSessionsData(sessionsData.filter((s) => s.session_id !== session_id))
        // If the deleted session was the active one, clear the chat
        if (currentSessionId === session_id) {
          setSessionId(null)
          clearChat()
        }
        toast.success('Session deleted')
      } else {
        const errorMsg = await response?.text()
        toast.error(
          `Failed to delete session: ${response?.statusText || 'Unknown error'} ${errorMsg || ''}`
        )
      }
    } catch (error) {
      toast.error(
        `Failed to delete session: ${error instanceof Error ? error.message : String(error)}`
      )
    } finally {
      setIsDeleteModalOpen(false)
      setIsDeleting(false)
    }
  }
  return (
    <>
      <div
        className={cn(
          'group flex h-11 w-full items-center justify-between rounded-lg px-3 py-2 transition-colors duration-200',
          isSelected
            ? 'cursor-default bg-primary/10'
            : 'cursor-pointer bg-background-secondary hover:bg-background-secondary/80'
        )}
        onClick={handleGetSession}
      >
        <div className="flex flex-col gap-1">
          <h4
            className={cn('text-sm font-medium', isSelected && 'text-primary')}
          >
            {truncateText(title, 20)}
          </h4>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="transform opacity-0 transition-all duration-200 ease-in-out group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation()
            setIsDeleteModalOpen(true)
          }}
        >
          <Icon type="trash" size="xs" />
        </Button>
      </div>
      <DeleteSessionModal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onDelete={handleDeleteSession}
        isDeleting={isDeleting}
      />
    </>
  )
}

export default SessionItem
