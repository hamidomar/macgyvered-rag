export const isTurboRefiLoanOfficer = (name?: string | null) =>
  /loa|loan officer/i.test(name || '')
