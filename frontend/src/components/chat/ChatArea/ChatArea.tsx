'use client'

import ChatInput from './ChatInput'
import MessageArea from './MessageArea'
import TurboRefiInsightPanel from './TurboRefiInsightPanel'
const ChatArea = () => {
  return (
    <main className="relative m-1.5 flex min-h-0 flex-grow flex-col rounded-xl bg-background">
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <MessageArea />
        </div>
        <TurboRefiInsightPanel />
      </div>
      <div className="shrink-0 border-t border-border bg-background px-4 pb-2 pt-3">
        <ChatInput />
      </div>
    </main>
  )
}

export default ChatArea
