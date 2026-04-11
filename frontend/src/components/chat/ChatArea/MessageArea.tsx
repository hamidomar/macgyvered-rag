'use client'

import { useState } from 'react'

import { useStore } from '@/store'
import Messages from './Messages'
import ScrollToBottom from '@/components/chat/ChatArea/ScrollToBottom'
import ToolCallDrawer from './Messages/ToolCallDrawer'
import type { ToolCall } from '@/types/os'
import { StickToBottom } from 'use-stick-to-bottom'

const MessageArea = () => {
  const { messages } = useStore()
  const [selectedToolCall, setSelectedToolCall] = useState<ToolCall | null>(null)

  return (
    <>
      <StickToBottom
        className="relative mb-4 flex max-h-[calc(100vh-64px)] min-h-0 flex-grow flex-col"
        resize="smooth"
        initial="smooth"
      >
        <StickToBottom.Content className="flex min-h-full flex-col justify-center">
          <div className="mx-auto w-full max-w-2xl space-y-9 px-4 pb-4">
            <Messages
              messages={messages}
              onToolSelect={(toolCall) => {
                setSelectedToolCall((current) =>
                  current?.tool_call_id === toolCall.tool_call_id ? null : toolCall
                )
              }}
              selectedToolCallId={selectedToolCall?.tool_call_id ?? null}
            />
          </div>
        </StickToBottom.Content>
        <ScrollToBottom />
      </StickToBottom>
      <ToolCallDrawer
        toolCall={selectedToolCall}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedToolCall(null)
          }
        }}
      />
    </>
  )
}

export default MessageArea
