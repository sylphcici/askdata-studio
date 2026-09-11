<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import { api } from "./api"
import ReportCard from "./components/ReportCard.vue"
import ResultTableCard from "./components/ResultTableCard.vue"
import EvaluationCenter from "./components/EvaluationCenter.vue"
import MarkdownReport from "./components/MarkdownReport.vue"
import type { AuthUser, ConversationRecord, QueryResult, ReportDataSource, SavedMemory, SchemaField, SchemaTable, WorkspaceConfig } from "./types"

interface HistoricalResultTable {
  taskId: string
  title: string
  query: string
  rowCount: number
  columns: string[]
  rows: Record<string, string | number | null>[]
}

const SAVED_TABLE_LIMIT = 8
const FIELD_LIBRARY_LIMIT = 12
const CONVERSATION_STORAGE_VERSION = 1
const COMMON_FIELD_LABELS = [
  "实付金额", "销售地区", "下单日期", "客户等级", "销售目标", "订单金额",
  "商品类别", "客户地区", "目标月份", "订单数量", "店铺名称", "用户等级",
]
const prompts = [
  "按订单地区统计各商品分类的销量",
  "按地区看平均单价",
  "按下单时间统计2026年7月各地区的订单量",
]
const input = ref("")
const loading = ref(false)
const pendingQuery = ref("")
const error = ref("")
const schema = ref<SchemaTable[]>([])
const savedMemories = ref<SavedMemory[]>([])
const fieldSearch = ref("")
const workspace = ref<WorkspaceConfig>({})
const conversations = ref<ConversationRecord[]>([])
const activeConversationId = ref("")
const expandedSql = ref<string | null>(null)
const copiedKey = ref<string | null>(null)
const leftOpen = ref(false)
const rightOpen = ref(false)
const conversationScroll = ref<HTMLElement | null>(null)
const composerInput = ref<HTMLTextAreaElement | null>(null)
const authUser = ref<AuthUser | null>(null)
const authReady = ref(false)
const loginLoading = ref(false)
const loginUsername = ref("")
const loginPassword = ref("")
const activeView = ref<"workspace" | "evaluation">("workspace")

let copyFeedbackTimer: ReturnType<typeof setTimeout> | undefined

async function copyText(text: string | null | undefined, key: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    if (copyFeedbackTimer) window.clearTimeout(copyFeedbackTimer)
    copyFeedbackTimer = window.setTimeout(() => {
      if (copiedKey.value === key) copiedKey.value = null
    }, 1500)
  } catch {
    error.value = "复制失败，请检查浏览器剪贴板权限"
  }
}

const activeConversation = computed(() =>
  conversations.value.find((item) => item.id === activeConversationId.value),
)
const confirmedFields = computed(() => workspace.value.schema_fields ?? [])
const analysisTableIds = computed(() => workspace.value.analysis_table_ids ?? [])
const historicalResultTables = computed<HistoricalResultTable[]>(() => {
  return savedMemories.value
    .filter((item) => item.kind === "result_table" && item.task_id && item.rows?.length)
    .map((item) => ({
      taskId: item.task_id!,
      title: item.title || "查询结果",
      query: item.query || "",
      rowCount: item.rows?.length || 0,
      columns: item.columns || [],
      rows: item.rows || [],
    }))
    .slice(0, SAVED_TABLE_LIMIT)
})
const reportDataSources = computed<ReportDataSource[]>(() => {
  const sources = new Map<string, ReportDataSource>()
  for (const conversation of conversations.value) {
    for (const turn of conversation.turns) {
      if (!turn.result.rows.length) continue
      sources.set(turn.result.task_id, {
        taskId: turn.result.task_id,
        title: turn.result.result_title || "查询结果",
        columns: turn.result.columns,
        rows: turn.result.rows,
      })
    }
  }
  for (const table of historicalResultTables.value) {
    sources.set(table.taskId, {
      taskId: table.taskId,
      title: table.title,
      columns: table.columns,
      rows: table.rows,
    })
  }
  return [...sources.values()]
})
const selectedAnalysisTables = computed(() =>
  analysisTableIds.value
    .map((id) => historicalResultTables.value.find((table) => table.taskId === id))
    .filter((table): table is HistoricalResultTable => Boolean(table)),
)
const recentFields = computed(() => {
  const items: { field: SchemaField; tableId: string }[] = []
  const keys = new Set<string>()
  const add = (fieldName: string, tableId: string) => {
    const table = schema.value.find((item) => item.id === tableId)
    const field = table?.fields.find((item) => item.name === fieldName)
    const key = `${tableId}:${fieldName}`
    if (field && !keys.has(key)) {
      keys.add(key)
      items.push({ field, tableId })
    }
  }
  for (const conversation of conversations.value) {
    for (const turn of [...conversation.turns].reverse()) {
      for (const field of turn.result.schema_graph?.fields ?? []) {
        if (field.source !== "relation_key") add(field.name, field.table_id)
      }
    }
    for (const field of conversation.workspace.schema_fields ?? conversation.workspace.fields ?? []) {
      const tableId = field.tableId
      if (tableId) add(field.name, tableId)
    }
  }
  return items.slice(0, FIELD_LIBRARY_LIMIT)
})
const savedFieldKeys = computed(() => new Set(
  savedMemories.value
    .filter((item) => item.kind === "schema_field")
    .map((item) => `${item.table_id}:${item.name}`),
))
const fieldLibrary = computed(() => {
  const items: { field: SchemaField; tableId: string; saved: boolean }[] = []
  const keys = new Set<string>()
  const add = (field: SchemaField, tableId: string, saved: boolean) => {
    const key = `${tableId}:${field.name}`
    if (keys.has(key)) return
    keys.add(key)
    items.push({ field, tableId, saved })
  }
  const searchTerm = fieldSearch.value.trim().toLocaleLowerCase()
  if (searchTerm) {
    for (const table of schema.value) {
      for (const field of table.fields) {
        const searchable = [
          field.label, field.name, field.description, ...(field.aliases ?? []),
          table.label, table.name, table.description, table.domain, ...(table.business_terms ?? []),
        ].filter(Boolean).join(" ").toLocaleLowerCase()
        if (searchable.includes(searchTerm)) {
          add(field, table.id, savedFieldKeys.value.has(`${table.id}:${field.name}`))
        }
      }
    }
    return items.slice(0, FIELD_LIBRARY_LIMIT)
  }
  for (const memory of savedMemories.value) {
    if (memory.kind !== "schema_field" || !memory.table_id || !memory.name) continue
    const field = findField(memory.name, memory.table_id) ?? {
      name: memory.name,
      label: memory.label || memory.name,
      type: memory.field_type || "文本",
    }
    add(field, memory.table_id, true)
  }
  for (const item of recentFields.value) {
    add(item.field, item.tableId, savedFieldKeys.value.has(`${item.tableId}:${item.field.name}`))
  }
  for (const label of COMMON_FIELD_LABELS) {
    const table = schema.value.find((candidate) => candidate.fields.some((field) => field.label === label))
    const field = table?.fields.find((candidate) => candidate.label === label)
    if (table && field) add(field, table.id, savedFieldKeys.value.has(`${table.id}:${field.name}`))
  }
  for (const table of schema.value) {
    for (const field of table.fields) {
      if (["metric", "dimension", "time"].includes(field.role ?? "")) {
        add(field, table.id, savedFieldKeys.value.has(`${table.id}:${field.name}`))
      }
    }
  }
  return items.slice(0, FIELD_LIBRARY_LIMIT)
})
const fieldLibraryLabel = computed(() => fieldSearch.value.trim() ? "搜索结果" : "常用与最近")
const historyGroups = computed(() => {
  const today = new Date().toDateString()
  const recent: ConversationRecord[] = []
  const earlier: ConversationRecord[] = []
  for (const item of conversations.value) {
    if (new Date(item.updatedAt).toDateString() === today) recent.push(item)
    else earlier.push(item)
  }
  return [
    { label: "今天", items: recent },
    { label: "更早", items: earlier },
  ].filter((group) => group.items.length)
})
const userRoleLabel = computed(() => {
  if (authUser.value?.role === "admin") return "全部数据权限"
  if (authUser.value?.role === "analyst") return "仅 Mock 数据"
  return "电商运营数据"
})

function closeMobilePanels() {
  leftOpen.value = false
  rightOpen.value = false
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === "Escape") closeMobilePanels()
}

onMounted(async () => {
  window.addEventListener("popstate", syncViewFromLocation)
  window.addEventListener("keydown", handleEscape)
  if (api.hasSession()) {
    try {
      authUser.value = await api.me()
    } catch {
      api.clearSession()
    }
  }
  authReady.value = true
  if (authUser.value) {
    syncViewFromLocation()
    await initializeUserWorkspace()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener("popstate", syncViewFromLocation)
  window.removeEventListener("keydown", handleEscape)
})

function syncViewFromLocation() {
  const wantsEvaluation = window.location.pathname === "/admin/evaluation"
  activeView.value = authUser.value?.role === "admin" && wantsEvaluation
    ? "evaluation"
    : "workspace"
  if (wantsEvaluation && authUser.value?.role !== "admin") {
    window.history.replaceState({}, "", "/")
  }
}

async function initializeUserWorkspace() {
  conversations.value = []
  activeConversationId.value = ""
  workspace.value = {}
  schema.value = []
  savedMemories.value = []
  restoreConversations()
  try {
    const [schemaResult, memories, remoteConversations] = await Promise.all([
      api.schema(),
      api.memories(),
      api.conversations(),
    ])
    schema.value = schemaResult
    savedMemories.value = memories
    mergeConversationHistory(remoteConversations)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "工作区加载失败"
  }
  if (!conversations.value.length) createConversation()
}

function selectAccount(username: string) {
  loginUsername.value = username
  loginPassword.value = ""
  error.value = ""
}

async function loginUser() {
  if (!loginUsername.value.trim() || !loginPassword.value || loginLoading.value) return
  loginLoading.value = true
  error.value = ""
  try {
    authUser.value = await api.login(loginUsername.value.trim(), loginPassword.value)
    syncViewFromLocation()
    await initializeUserWorkspace()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "登录失败"
  } finally {
    loginLoading.value = false
  }
}

async function logoutUser() {
  if (loading.value) return
  try {
    await api.logout()
  } finally {
    authUser.value = null
    conversations.value = []
    activeConversationId.value = ""
    workspace.value = {}
    schema.value = []
    savedMemories.value = []
    input.value = ""
    error.value = ""
    activeView.value = "workspace"
    window.history.replaceState({}, "", "/")
  }
}

function openEvaluationCenter() {
  if (authUser.value?.role !== "admin") return
  activeView.value = "evaluation"
  leftOpen.value = false
  window.history.pushState({}, "", "/admin/evaluation")
}

function openWorkspace() {
  activeView.value = "workspace"
  leftOpen.value = false
  window.history.pushState({}, "", "/")
}

function normalizeWorkspace(value?: WorkspaceConfig): WorkspaceConfig {
  const fields = value?.schema_fields ?? value?.fields ?? []
  return {
    schema_fields: Array.isArray(fields)
      ? fields.map((field) => ({ name: field.name, tableId: field.tableId, aggregation: "auto" as const }))
      : [],
    analysis_table_ids: Array.isArray(value?.analysis_table_ids)
      ? [...value.analysis_table_ids]
      : [],
  }
}

function conversationStorageKey() {
  return authUser.value ? `askdata_conversations_v${CONVERSATION_STORAGE_VERSION}:${authUser.value.user_id}` : ""
}

function restoreConversations() {
  const key = conversationStorageKey()
  if (!key) return
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return
    const stored = JSON.parse(raw) as {
      activeConversationId?: unknown
      conversations?: unknown
    }
    if (!Array.isArray(stored.conversations)) return
    conversations.value = stored.conversations
      .filter((item): item is ConversationRecord => Boolean(
        item
        && typeof item === "object"
        && typeof item.id === "string"
        && typeof item.title === "string"
        && Array.isArray(item.turns),
      ))
      .map((item) => ({
        ...item,
        updatedAt: Number(item.updatedAt) || Date.now(),
        workspace: normalizeWorkspace(item.workspace),
      }))
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, 30)
    const requestedId = typeof stored.activeConversationId === "string"
      ? stored.activeConversationId
      : ""
    activeConversationId.value = conversations.value.some((item) => item.id === requestedId)
      ? requestedId
      : conversations.value[0]?.id ?? ""
    workspace.value = normalizeWorkspace(activeConversation.value?.workspace)
  } catch {
    localStorage.removeItem(key)
  }
}

function persistConversations() {
  const key = conversationStorageKey()
  if (!key) return
  try {
    localStorage.setItem(key, JSON.stringify({
      activeConversationId: activeConversationId.value,
      conversations: conversations.value,
    }))
  } catch (caught) {
    console.warn("Unable to persist conversation history", caught)
  }
}

function syncConversation(conversation: ConversationRecord) {
  void api.saveConversation(conversation).catch((caught) => {
    console.warn("Unable to sync conversation", caught)
  })
}

function mergeConversationHistory(remote: ConversationRecord[]) {
  const local = conversations.value
  const source = remote.length ? remote : local
  conversations.value = source
    .map((item) => ({ ...item, workspace: normalizeWorkspace(item.workspace) }))
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, 30)
  activeConversationId.value = conversations.value.some((item) => item.id === activeConversationId.value)
    ? activeConversationId.value
    : conversations.value[0]?.id ?? ""
  workspace.value = normalizeWorkspace(activeConversation.value?.workspace)
  persistConversations()
  if (!remote.length) {
    for (const item of conversations.value) syncConversation(item)
  }
}

function tidyConversations() {
  conversations.value.sort((a, b) => b.updatedAt - a.updatedAt)
  conversations.value = conversations.value.slice(0, 30)
  persistConversations()
}

function createConversationId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID()
  }

  const bytes = new Uint8Array(16)
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`
}

function createConversation() {
  if (activeView.value !== "workspace") openWorkspace()
  if (loading.value) return
  const existingEmpty = conversations.value.find((item) => !item.turns.length)
  if (existingEmpty) {
    selectConversation(existingEmpty.id)
    return
  }
  const item: ConversationRecord = {
    id: createConversationId(),
    title: "新对话",
    updatedAt: Date.now(),
    turns: [],
    workspace: {},
  }
  conversations.value.unshift(item)
  activeConversationId.value = item.id
  workspace.value = {}
  input.value = ""
  error.value = ""
  leftOpen.value = false
  tidyConversations()
  syncConversation(item)
}

function selectConversation(id: string) {
  if (activeView.value !== "workspace") openWorkspace()
  const item = conversations.value.find((conversation) => conversation.id === id)
  if (!item) return
  activeConversationId.value = id
  workspace.value = normalizeWorkspace(item.workspace)
  input.value = ""
  error.value = ""
  leftOpen.value = false
  persistConversations()
  nextTick(() => conversationScroll.value?.scrollTo({ top: conversationScroll.value.scrollHeight }))
}

function removeConversation(id: string) {
  conversations.value = conversations.value.filter((item) => item.id !== id)
  void api.deleteConversation(id).catch((caught) => {
    console.warn("Unable to delete conversation", caught)
  })
  if (activeConversationId.value === id) {
    if (conversations.value[0]) selectConversation(conversations.value[0].id)
    else createConversation()
  }
  tidyConversations()
}

function saveActiveConversation() {
  const conversation = activeConversation.value
  if (!conversation) return
  conversation.workspace = normalizeWorkspace(workspace.value)
  conversation.updatedAt = Date.now()
  if (conversation.title === "新对话" && conversation.turns[0]) {
    conversation.title = conversation.turns[0].query.slice(0, 18)
  }
  tidyConversations()
  syncConversation(conversation)
}

function failureMessage(result: QueryResult) {
  const detail = result.analysis || ""
  if (/JOIN|关联关系|关联字段/i.test(detail)) {
    return "系统没有找到可靠的数据表关联方式，请明确统计对象或字段归属后重新提问。"
  }
  if (/字段|column|binder|schema/i.test(detail)) {
    return "系统没有找到与问题匹配的可靠字段，请换用更明确的业务名称后重试。"
  }
  if (/timeout|超时/i.test(detail)) {
    return "查询服务暂时超时，你可以直接重试。"
  }
  return "本次查询没有成功完成，你可以重试或补充查询口径后重新提问。"
}

function failureSuggestions(result: QueryResult) {
  const detail = result.analysis || ""
  if (/JOIN|关联关系|关联字段/i.test(detail)) {
    return ["说明按哪个业务对象统计", "说明同名字段的归属，例如订单地区或店铺地区"]
  }
  if (/字段|column|binder|schema/i.test(detail)) {
    return ["换用页面中已有的业务字段名称", "补充指标、维度和筛选条件"]
  }
  return ["检查并补充指标、维度、时间范围", "换一种更明确的说法后重新提问"]
}

function reviseQuery(query: string) {
  input.value = query
  nextTick(() => composerInput.value?.focus())
}

async function submit(text?: string) {
  const query = (text ?? input.value).trim()
  if (!query || loading.value) return
  if (!activeConversation.value) createConversation()
  loading.value = true
  pendingQuery.value = query
  error.value = ""
  input.value = ""
  try {
    const requestWorkspace: WorkspaceConfig = {
      ...workspace.value,
      analysis_tables: selectedAnalysisTables.value.map((table) => ({
        task_id: table.taskId,
        title: table.title,
        query: table.query,
        columns: table.columns,
        rows: table.rows.slice(0, 50),
      })),
    }
    const result = await api.query(
      query,
      requestWorkspace,
      activeConversation.value?.id ?? "studio-demo",
    )
    activeConversation.value?.turns.push({ query, result })
    saveActiveConversation()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "查询失败"
    input.value = query
  } finally {
    loading.value = false
    pendingQuery.value = ""
  }
}

async function saveResult(result: QueryResult) {
  await api.save(result.task_id)
  result.saved = true
  savedMemories.value = await api.memories()
  saveActiveConversation()
}

async function deleteSavedResult(table: HistoricalResultTable) {
  if (!window.confirm(`确定删除结果表“${table.title}”吗？`)) return
  await api.deleteMemory(`result:${table.taskId}`)
  savedMemories.value = await api.memories()
  workspace.value.analysis_table_ids = analysisTableIds.value.filter((id) => id !== table.taskId)
  for (const conversation of conversations.value) {
    conversation.workspace.analysis_table_ids = (conversation.workspace.analysis_table_ids ?? [])
      .filter((id) => id !== table.taskId)
    for (const turn of conversation.turns) {
      if (turn.result.task_id === table.taskId) turn.result.saved = false
    }
  }
  saveActiveConversation()
}

async function toggleSavedField(field: SchemaField, tableId: string) {
  const memoryId = `field:${tableId}.${field.name}`
  if (savedFieldKeys.value.has(`${tableId}:${field.name}`)) {
    await api.deleteMemory(memoryId)
  } else {
    await api.saveField(tableId, field)
  }
  savedMemories.value = await api.memories()
}

function isSavedField(fieldName: string, tableId?: string) {
  return Boolean(tableId && savedFieldKeys.value.has(`${tableId}:${fieldName}`))
}

function toggleConfirmedFieldMemory(fieldName: string, tableId?: string) {
  const field = findField(fieldName, tableId)
  if (field && tableId) toggleSavedField(field, tableId)
}

function resetWorkspace() {
  workspace.value = {}
  saveActiveConversation()
}

function dragAnalysisTable(event: DragEvent, table: HistoricalResultTable) {
  event.dataTransfer?.setData("analysis-result-table", table.taskId)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy"
}

function addAnalysisTable(taskId: string) {
  if (!historicalResultTables.value.some((table) => table.taskId === taskId) || analysisTableIds.value.includes(taskId)) return
  workspace.value.analysis_table_ids = [...analysisTableIds.value, taskId]
  saveActiveConversation()
}

function dropAnalysisTable(event: DragEvent) {
  addAnalysisTable(event.dataTransfer?.getData("analysis-result-table") ?? "")
}

function removeAnalysisTable(taskId: string) {
  workspace.value.analysis_table_ids = analysisTableIds.value.filter((id) => id !== taskId)
  saveActiveConversation()
}

function dragField(event: DragEvent, field: SchemaField, tableId: string) {
  event.dataTransfer?.setData("field", field.name)
  event.dataTransfer?.setData("field-table", tableId)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy"
}

function findField(fieldName: string, tableId?: string) {
  const selectedTable = tableId ? schema.value.find((table) => table.id === tableId) : undefined
  return selectedTable?.fields.find((field) => field.name === fieldName)
    ?? schema.value.flatMap((table) => table.fields).find((field) => field.name === fieldName)
}

function isNumericField(fieldName: string, tableId?: string) {
  const field = findField(fieldName, tableId)
  return field?.type === "数值" || field?.type === "整数"
}

function addConfirmedField(fieldName: string, sourceTableId?: string) {
  const tableId = sourceTableId
  if (!tableId || !findField(fieldName, tableId)) return
  if (confirmedFields.value.some((field) => field.name === fieldName && field.tableId === tableId)) return
  workspace.value.schema_fields = [
    ...confirmedFields.value,
    {
      name: fieldName,
      aggregation: "auto",
      tableId,
    },
  ]
  saveActiveConversation()
}

function dropConfirmedField(event: DragEvent) {
  addConfirmedField(
    event.dataTransfer?.getData("field") ?? "",
    event.dataTransfer?.getData("field-table") ?? undefined,
  )
}

function removeConfirmedField(fieldName: string, tableId?: string) {
  workspace.value.schema_fields = confirmedFields.value.filter(
    (field) => !(field.name === fieldName && field.tableId === tableId),
  )
  saveActiveConversation()
}

function fieldLabel(fieldName: string, tableId?: string) {
  return findField(fieldName, tableId)?.label ?? fieldName
}

function tableLabel(tableId?: string) {
  return schema.value.find((table) => table.id === tableId)?.label ?? "未知数据表"
}

function clarificationHint(result: QueryResult) {
  return result.clarification?.options.map((option) => option.label).join("、") ?? ""
}

function queryFilters(result: QueryResult) {
  const extraction = result.retrieval?.extraction
  const timeFieldTerms = result.schema_graph?.fields
    .filter((field) => field.role === "time")
    .flatMap((field) => [field.name, field.sql_name || "", field.label]) ?? []
  const normalize = (value: string) => value.toLowerCase().replace(/[\s年月日/.:-]/g, "")
  const timeTerms = [...(extraction?.time_expressions ?? []), ...timeFieldTerms]
    .map(normalize)
    .filter(Boolean)
  const isTimeFilter = (value: string) => {
    const normalized = normalize(value)
    return timeTerms.some((term) => normalized.includes(term))
      || /(?:^|\D)\d{4}[-年/.]\d{1,2}(?:[-月/.]\d{1,2})?/.test(value)
      || /(本月|这个月|当月|上月|下月|本年|今年|去年|今天|昨日|昨天|季度|年度|最近\s*\d*\s*[天日周月年])/.test(value)
  }
  const filters = extraction?.filters
    ?.flatMap((item) => item.split(/\s+and\s+|[，,、；;]/i))
    .map((item) => item.trim())
    .filter((item) => item && !isTimeFilter(item)) ?? []
  return filters.length ? [...new Set(filters)].join("、") : "无"
}

function sqlFieldName(field: { name: string; sql_name?: string }) {
  return (field.sql_name || field.name).split(".").pop() || field.name
}

function queryDataTables(result: QueryResult) {
  if (!result.sql || !result.schema_graph) return result.interpretation?.table || "暂无法可靠识别"
  const tableByName = new Map<string, (typeof result.schema_graph.tables)[number]>()
  for (const table of result.schema_graph.tables) {
    tableByName.set((table.name || table.id).toLowerCase(), table)
    tableByName.set(table.id.toLowerCase(), table)
  }
  const used = [...result.sql.matchAll(/\b(?:from|join)\s+["`]?([a-z_][\w]*)["`]?/gi)]
    .map((match) => tableByName.get(match[1].toLowerCase()))
    .filter((table): table is (typeof result.schema_graph.tables)[number] => Boolean(table))
  const labels = [...new Set(used.map((table) => table.label))]
  return labels.length ? labels.join("、") : result.interpretation?.table || "暂无法可靠识别"
}

function queryKeyFields(result: QueryResult) {
  if (!result.sql || !result.schema_graph) return []
  const sql = result.sql
  const tables = result.schema_graph.tables
  const reserved = new Set(["where", "join", "left", "right", "inner", "outer", "full", "cross", "on", "group", "order", "limit", "having", "union"])
  const tableByName = new Map<string, (typeof tables)[number]>()
  const aliases = new Map<string, (typeof tables)[number]>()

  for (const table of tables) {
    tableByName.set((table.name || table.id).toLowerCase(), table)
    tableByName.set(table.id.toLowerCase(), table)
  }
  for (const match of sql.matchAll(/\b(?:from|join)\s+["`]?([a-z_][\w]*)["`]?(?:\s+(?:as\s+)?([a-z_][\w]*))?/gi)) {
    const table = tableByName.get(match[1].toLowerCase())
    if (!table) continue
    aliases.set(match[1].toLowerCase(), table)
    if (match[2] && !reserved.has(match[2].toLowerCase())) aliases.set(match[2].toLowerCase(), table)
  }

  const normalizedSql = sql.toLowerCase()
  const usedTableIds = new Set([...aliases.values()].map((table) => table.id))
  const nameCounts = new Map<string, number>()
  for (const field of result.schema_graph.fields) {
    if (!usedTableIds.has(field.table_id)) continue
    const name = sqlFieldName(field).toLowerCase()
    nameCounts.set(name, (nameCounts.get(name) || 0) + 1)
  }

  return result.schema_graph.fields.flatMap((field) => {
    const fieldName = sqlFieldName(field).toLowerCase()
    const table = tables.find((item) => item.id === field.table_id)
    if (!table) return []
    const tableAliases = [...aliases.entries()]
      .filter(([, resolved]) => resolved.id === table.id)
      .map(([alias]) => alias)
    const qualifiedPattern = tableAliases.some((alias) =>
      new RegExp(`\\b${alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\.\\s*[\"\`]?${fieldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(sql)
    )
    const unqualifiedPattern = nameCounts.get(fieldName) === 1
      && tableAliases.length > 0
      && new RegExp(`\\b${fieldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(normalizedSql)
    if (!qualifiedPattern && !unqualifiedPattern) return []
    return [{
      id: `${field.table_id}.${fieldName}`,
      label: field.label || field.name,
      tableLabel: table.label,
      technical: (field.sql_name || "").includes(".")
        ? field.sql_name!
        : `${table.name || table.id}.${fieldName}`,
    }]
  })
}

</script>

<template>
  <div v-if="!authReady" class="auth-loading"><span></span><p>正在连接 AskData…</p></div>

  <main v-else-if="!authUser" class="login-page">
    <section class="login-intro">
      <div class="login-brand"><span>A</span><strong>AskData</strong></div>
      <div>
        <p class="kicker">TRUSTED TEXT-TO-SQL</p>
        <h1>让每个人，<br>都能直接向数据提问。</h1>
        <p>从自然语言到可信 SQL 与可解释结果，内置字段级 Schema 检索、只读安全、角色权限隔离与自动化质量评测。</p>
      </div>
      <small>FastAPI · LangGraph · Vue · 可追溯评测</small>
    </section>

    <section class="login-side">
      <form class="login-card" @submit.prevent="loginUser">
        <header><span class="login-mark">A</span><div><h2>欢迎回来</h2><p>登录 AskData Studio</p></div></header>
        <label>
          <span>账号</span>
          <input v-model="loginUsername" autocomplete="username" placeholder="请输入账号">
        </label>
        <label>
          <span>密码</span>
          <input v-model="loginPassword" type="password" autocomplete="current-password" placeholder="请输入密码">
        </label>
        <p v-if="error" class="login-error">{{ error }}</p>
        <button class="login-submit" :disabled="loginLoading" type="submit">
          {{ loginLoading ? "正在登录…" : "登录" }}
        </button>

        <div class="mock-accounts">
          <p>可用角色</p>
          <button type="button" @click="selectAccount('admin')">
            <span class="account-icon admin">管</span>
            <span><strong>admin</strong><small>管理员 · 全部数据</small></span>
            <code>选择</code>
          </button>
          <button type="button" @click="selectAccount('sales')">
            <span class="account-icon user">销</span>
            <span><strong>sales</strong><small>电商运营 · ecommerce_ops</small></span>
            <code>选择</code>
          </button>
          <button type="button" @click="selectAccount('mock')">
            <span class="account-icon mock">示</span>
            <span><strong>mock</strong><small>基础演示 · askdata_mock</small></span>
            <code>选择</code>
          </button>
        </div>
        <small class="login-note">点击选择角色后，请输入部署时配置的密码。</small>
      </form>
    </section>
  </main>

  <div v-else class="app-layout" :class="{ 'evaluation-layout': activeView === 'evaluation' }">
    <button
      v-if="leftOpen || rightOpen"
      class="mobile-backdrop"
      type="button"
      aria-label="关闭侧栏"
      @click="closeMobilePanels"
    ></button>
    <aside class="history-sidebar" :class="{ open: leftOpen }">
      <div class="brand-row">
        <span class="brand-symbol">A</span>
        <div><strong>AskData</strong><small>AI 数据分析</small></div>
        <button class="mobile-panel-close" type="button" aria-label="关闭对话历史" @click="leftOpen = false">×</button>
      </div>

      <button class="new-chat" :class="{ active: activeView === 'workspace' }" :disabled="loading || (activeView === 'workspace' && !activeConversation?.turns.length)" @click="createConversation"><span>＋</span>新建对话</button>

      <nav class="history-list" aria-label="对话历史">
        <section v-for="group in historyGroups" :key="group.label">
          <p>{{ group.label }}</p>
          <div
            v-for="item in group.items"
            :key="item.id"
            class="history-item"
            :class="{ active: item.id === activeConversationId }"
          >
            <button class="history-select" @click="selectConversation(item.id)">
              <span class="chat-icon">◌</span>
              <span><strong>{{ item.title }}</strong><small>{{ item.turns.length }} 轮对话</small></span>
            </button>
            <button class="history-remove" aria-label="删除对话" @click="removeConversation(item.id)">×</button>
          </div>
        </section>
      </nav>

      <nav v-if="authUser.role === 'admin'" class="admin-navigation" aria-label="管理员功能">
        <p>管理工具</p>
        <button :class="{ active: activeView === 'evaluation' }" @click="openEvaluationCenter">
          <span>✓</span><span><strong>评测中心</strong><small>模型质量与回归报告</small></span>
        </button>
      </nav>

      <div class="history-footer">
        <div class="user-avatar">{{ authUser.display_name.slice(0, 1) }}</div>
        <div class="history-user"><strong>{{ authUser.display_name }}</strong><small><i></i> {{ userRoleLabel }}</small></div>
        <button class="logout-button" @click="logoutUser">退出</button>
      </div>
    </aside>

    <EvaluationCenter v-if="activeView === 'evaluation'" />

    <main v-else class="chat-column">
      <header class="chat-header">
        <button class="mobile-menu" @click="leftOpen = !leftOpen; rightOpen = false">☰</button>
        <div>
          <strong>{{ activeConversation?.title ?? "新对话" }}</strong>
          <span>自然语言问数</span>
        </div>
        <button class="config-trigger" @click="rightOpen = !rightOpen; leftOpen = false">上下文设置</button>
        <span class="model-state"><i></i> 智能确认模式</span>
      </header>

      <section ref="conversationScroll" class="conversation-scroll">
        <Transition name="conversation" mode="out-in">
        <div :key="activeConversationId" class="conversation-view">
        <div v-if="!activeConversation?.turns.length && !loading" class="welcome-panel">
          <div class="welcome-copy">
            <span class="welcome-mark">✦</span>
            <p class="kicker">ASKDATA STUDIO</p>
            <h1>想从数据里了解什么？</h1>
            <p>查询结果会以清晰的表格卡片展示，并支持分页和Excel导出。</p>
            <div class="prompt-list">
              <button v-for="prompt in prompts" :key="prompt" @click="submit(prompt)">
                <span>↗</span>{{ prompt }}
              </button>
            </div>
          </div>
        </div>

        <div v-else class="thread">
          <article v-for="(turn, turnIndex) in activeConversation?.turns" :key="`${turn.result.task_id}:${turnIndex}`" class="turn">
            <div class="user-message">
              <div class="message-avatar user">你</div>
              <div class="message-body">
                <div class="message-meta"><small>你</small></div>
                <p>{{ turn.query }}</p>
                <div class="message-actions user-actions">
                  <button class="icon-action" type="button" :title="copiedKey === `query:${turn.result.task_id}` ? '已复制' : '复制问题'" :aria-label="copiedKey === `query:${turn.result.task_id}` ? '已复制' : '复制问题'" @click="copyText(turn.query, `query:${turn.result.task_id}`)">
                    <span v-if="copiedKey === `query:${turn.result.task_id}`">✓</span>
                    <svg v-else viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>
                  </button>
                </div>
              </div>
            </div>

            <div class="assistant-message">
              <div class="message-avatar assistant">A</div>
              <div class="message-body assistant-body">
                <div class="answer-heading" :class="{ 'qa-heading': turn.result.route !== 'database_query' }">
                  <div><small>AskData</small><strong v-if="turn.result.route === 'database_query'">{{ turn.result.status === "failed" ? "处理失败" : turn.result.status === "waiting_clarification" ? "需要补充信息" : "查询完成" }}</strong></div>
                  <span v-if="turn.result.route === 'database_query' && turn.result.status === 'completed'">
                    {{ turn.result.workflow_mode === "single_database_agent" ? "单库智能体" : "多库流程" }}
                  </span>
                </div>

                <div v-if="turn.result.status === 'waiting_clarification'" class="natural-clarification">
                  <p>{{ turn.result.clarification?.question }}</p>
                  <small>{{ turn.result.clarification?.reason }}</small>
                  <div v-if="turn.result.clarification?.options.length" class="clarification-options">
                    <button
                      v-for="option in turn.result.clarification.options"
                      :key="option.id"
                      type="button"
                      :disabled="loading"
                      :title="option.description"
                      @click="submit(option.label)"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                  <span v-if="clarificationHint(turn.result)">也可以直接输入其他指标</span>
                </div>

                <details v-if="turn.result.retrieval && turn.result.status !== 'waiting_clarification'" class="execution-details">
                  <summary>查看检索过程</summary>
                  <div class="execution-strip">
                    <span>BM25 {{ turn.result.retrieval.bm25_count }} · Dense {{ turn.result.retrieval.dense_count }}</span>
                    <span>RRF {{ turn.result.retrieval.rrf_count }} → Rerank {{ turn.result.retrieval.selected_count }} 字段</span>
                    <span>阈值 ≥ {{ turn.result.retrieval.threshold.toFixed(2) }}</span>
                    <span v-if="turn.result.schema_graph">Schema 图 {{ turn.result.schema_graph.tables.length }} 表 · {{ turn.result.schema_graph.fields.length }} 字段</span>
                  </div>
                </details>

                <div
                  v-if="turn.result.standalone_query && turn.result.standalone_query !== turn.query"
                  class="standalone-query"
                >
                  <small>已结合上文补全</small>
                  <span>{{ turn.result.standalone_query }}</span>
                </div>

                <div v-if="turn.result.analysis_sources?.length" class="analysis-source-strip">
                  <strong>综合分析来源</strong>
                  <span v-for="source in turn.result.analysis_sources" :key="source.task_id">
                    ▦ {{ source.title }} · {{ source.row_count }} 行
                  </span>
                </div>

                <div v-if="turn.result.interpretation" class="scope-card">
                  <div class="scope-head"><strong>本次查询口径</strong><span>系统识别，请核对</span></div>
                  <div class="scope-grid">
                    <div><small>数据表</small><strong>{{ queryDataTables(turn.result) }}</strong></div>
                    <div><small>指标</small><strong>{{ turn.result.interpretation.metric }}</strong></div>
                    <div><small>维度</small><strong>{{ turn.result.interpretation.dimension }}</strong></div>
                    <div><small>时间范围</small><strong>{{ turn.result.interpretation.time_range }}</strong></div>
                    <div><small>筛选条件</small><strong>{{ queryFilters(turn.result) }}</strong></div>
                    <div class="scope-key-fields">
                      <small>关键字段</small>
                      <span v-if="queryKeyFields(turn.result).length" class="scope-field-list">
                        <span
                          v-for="field in queryKeyFields(turn.result)"
                          :key="field.id"
                          class="scope-field"
                          :title="field.technical"
                        >
                          <strong>{{ field.label }}（{{ field.tableLabel }}）</strong>
                          <span class="scope-field-tech">{{ field.technical }}</span>
                        </span>
                      </span>
                      <strong v-else>暂无法可靠识别</strong>
                    </div>
                  </div>
                </div>

                <div v-if="turn.result.route === 'database_query' && turn.result.status === 'failed'" class="failure-recovery">
                  <strong>这次没有查成功</strong>
                  <p>{{ failureMessage(turn.result) }}</p>
                  <small>你可以：</small>
                  <ul>
                    <li v-for="suggestion in failureSuggestions(turn.result)" :key="suggestion">{{ suggestion }}</li>
                  </ul>
                  <div class="failure-actions">
                    <button type="button" :disabled="loading" @click="submit(turn.query)">重新尝试</button>
                    <button type="button" :disabled="loading" @click="reviseQuery(turn.result.standalone_query || turn.query)">修改问题</button>
                  </div>
                  <details v-if="turn.result.analysis || turn.result.sql" class="failure-technical">
                    <summary>查看技术详情</summary>
                    <p v-if="turn.result.analysis">{{ turn.result.analysis }}</p>
                    <pre v-if="turn.result.sql"><code>{{ turn.result.sql }}</code></pre>
                  </details>
                </div>

                <ReportCard
                  v-if="turn.result.report"
                  :report="turn.result.report"
                  :sources="reportDataSources"
                />

                <MarkdownReport
                  v-else-if="turn.result.route !== 'database_query' && turn.result.analysis"
                  class="qa-answer"
                  :markdown="turn.result.analysis"
                />

                <ResultTableCard
                  v-if="turn.result.route === 'database_query' && turn.result.status === 'completed' && turn.result.rows.length"
                  :title="turn.result.result_title || '查询结果'"
                  :columns="turn.result.columns"
                  :rows="turn.result.rows"
                  :task-id="turn.result.task_id"
                  :total-row-count="turn.result.total_row_count"
                  :rows-truncated="turn.result.rows_truncated"
                >
                  <template #actions>
                      <button v-if="turn.result.sql" @click="expandedSql = expandedSql === turn.result.task_id ? null : turn.result.task_id">SQL</button>
                      <button v-if="turn.result.sql" class="toolbar-icon-action" :title="copiedKey === `sql:${turn.result.task_id}` ? '已复制' : '复制 SQL'" :aria-label="copiedKey === `sql:${turn.result.task_id}` ? '已复制' : '复制 SQL'" @click="copyText(turn.result.sql, `sql:${turn.result.task_id}`)">
                        <span v-if="copiedKey === `sql:${turn.result.task_id}`">✓</span>
                        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>
                      </button>
                      <button class="save-result" :disabled="turn.result.saved" @click="saveResult(turn.result)">{{ turn.result.saved ? "已保存" : "保存" }}</button>
                  </template>
                  <template #details>
                    <pre v-if="expandedSql === turn.result.task_id && turn.result.sql"><code>{{ turn.result.sql }}</code></pre>
                  </template>
                </ResultTableCard>

                <div
                  v-if="turn.result.route === 'database_query' && turn.result.analysis && turn.result.status === 'completed'"
                  class="result-analysis"
                >
                  <strong>结果说明</strong>
                  <MarkdownReport class="analysis-markdown" :markdown="turn.result.analysis" />
                  <div class="message-actions">
                    <button class="icon-action" type="button" :title="copiedKey === `analysis:${turn.result.task_id}` ? '已复制' : '复制结果说明'" :aria-label="copiedKey === `analysis:${turn.result.task_id}` ? '已复制' : '复制结果说明'" @click="copyText(turn.result.analysis, `analysis:${turn.result.task_id}`)">
                      <span v-if="copiedKey === `analysis:${turn.result.task_id}`">✓</span>
                      <svg v-else viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </article>

          <div v-if="loading && pendingQuery" class="user-message pending-user-message">
            <div class="message-avatar user">你</div>
            <div class="message-body"><small>你 · 已发送</small><p>{{ pendingQuery }}</p></div>
          </div>

          <div v-if="loading" class="assistant-message loading-message">
            <div class="message-avatar assistant">A</div>
            <div class="loading-copy"><span></span><div><strong>正在分析</strong><small>理解问题并检索相关 Schema…</small></div></div>
          </div>
        </div>
        </div>
        </Transition>

        <div v-if="error" class="error-banner">{{ error }}</div>
      </section>

      <footer class="composer">
        <div class="composer-box">
          <textarea ref="composerInput" v-model="input" rows="1" placeholder="向数据提问…" @keydown.enter.exact.prevent="submit()"></textarea>
          <div class="composer-meta">
            <span>问数 {{ confirmedFields.length }} 个字段 · 分析 {{ selectedAnalysisTables.length }} 张结果表</span>
            <button :disabled="!input.trim() || loading" @click="submit()">↑</button>
          </div>
        </div>
        <small>模型可能产生偏差，缺少关键业务口径时会在对话中继续询问。</small>
      </footer>
    </main>

    <aside v-if="activeView === 'workspace'" class="query-panel" :class="{ open: rightOpen }">
      <div class="panel-header">
        <div><p class="kicker">CONTEXT CONTROL</p><h2>本次上下文</h2></div>
        <div class="panel-actions">
          <button @click="resetWorkspace">清空</button>
          <button class="mobile-panel-close" type="button" aria-label="关闭上下文设置" @click="rightOpen = false">×</button>
        </div>
      </div>

      <section class="context-block query-context-block">
        <div class="context-heading">
          <div><strong>查询字段</strong><small>用于生成 SQL</small></div>
          <em>{{ confirmedFields.length }} 个</em>
        </div>
        <div
          class="confirmed-fields-zone"
          :class="{ filled: confirmedFields.length }"
          @dragover.prevent
          @drop.prevent="dropConfirmedField"
        >
          <div v-if="!confirmedFields.length" class="empty-confirmation">
            <span>＋</span>
            <strong>拖入字段</strong>
          </div>
          <div v-for="field in confirmedFields" :key="`${field.tableId}:${field.name}`" class="confirmed-field">
            <span class="field-badge">{{ isNumericField(field.name, field.tableId) ? "#" : "T" }}</span>
            <span class="confirmed-field-name"><strong>{{ fieldLabel(field.name, field.tableId) }}</strong><small>{{ tableLabel(field.tableId) }}</small></span>
            <button class="save-field" :class="{ saved: isSavedField(field.name, field.tableId) }" :aria-label="`保存${fieldLabel(field.name, field.tableId)}`" @click="toggleConfirmedFieldMemory(field.name, field.tableId)">{{ isSavedField(field.name, field.tableId) ? "★" : "☆" }}</button>
            <button class="remove-field" :aria-label="`移除${fieldLabel(field.name, field.tableId)}`" @click="removeConfirmedField(field.name, field.tableId)">×</button>
          </div>
        </div>
      </section>

      <section class="context-block analysis-context-block">
        <div class="context-heading">
          <div><strong>参考结果</strong><small>用于综合分析</small></div>
          <em>{{ selectedAnalysisTables.length }} 张</em>
        </div>
        <div
          class="analysis-tables-zone"
          :class="{ filled: selectedAnalysisTables.length }"
          @dragover.prevent
          @drop.prevent="dropAnalysisTable"
        >
          <div v-if="!selectedAnalysisTables.length" class="empty-confirmation">
            <span>＋</span>
            <strong>拖入已保存结果</strong>
          </div>
          <div v-for="table in selectedAnalysisTables" :key="table.taskId" class="analysis-table-chip">
            <span class="table-mark">▦</span>
            <span><strong>{{ table.title }}</strong><small>{{ table.rowCount }} 行 · {{ table.columns.slice(0, 3).join(" / ") }}</small></span>
            <button :aria-label="`移除${table.title}`" @click="removeAnalysisTable(table.taskId)">×</button>
          </div>
        </div>
      </section>

      <section class="recent-library">
        <div class="library-heading">
          <div><strong>字段与结果</strong><small>搜索、拖拽或双击添加</small></div>
        </div>
        <label class="field-search">
          <span aria-hidden="true">⌕</span>
          <input v-model="fieldSearch" type="search" placeholder="搜索字段名称、含义或所属表" aria-label="搜索字段" />
        </label>
        <div class="recent-columns">
          <div class="recent-column">
            <p>{{ fieldLibraryLabel }} · 最多 {{ FIELD_LIBRARY_LIMIT }} 个</p>
            <div v-if="!fieldLibrary.length" class="library-empty">未找到匹配字段，请尝试业务名称或所属表</div>
            <div
              v-for="item in fieldLibrary"
              :key="`${item.tableId}:${item.field.name}`"
              class="field-library-row"
              draggable="true"
              @dragstart="dragField($event, item.field, item.tableId)"
            >
              <button class="recent-card field-card" @dblclick="addConfirmedField(item.field.name, item.tableId)">
                <span class="field-badge">{{ item.field.type === "数值" || item.field.type === "整数" ? "#" : "T" }}</span>
                <span><strong>{{ item.field.label }}</strong><small>{{ tableLabel(item.tableId) }}</small></span>
              </button>
              <button class="save-field" :class="{ saved: item.saved }" :aria-label="`${item.saved ? '取消收藏' : '收藏'}${item.field.label}`" @click="toggleSavedField(item.field, item.tableId)">{{ item.saved ? "★" : "☆" }}</button>
            </div>
          </div>
          <div class="recent-column">
            <p>结果表 · 最多 {{ SAVED_TABLE_LIMIT }} 张</p>
            <div v-if="!historicalResultTables.length" class="library-empty">保存查询结果后显示</div>
            <div
              v-for="table in historicalResultTables"
              :key="table.taskId"
              class="result-library-row"
              draggable="true"
              @dragstart="dragAnalysisTable($event, table)"
            >
              <button
                class="recent-card table-card"
                :aria-label="`${table.title}，${table.rowCount}行，查询：${table.query}`"
                @dblclick="addAnalysisTable(table.taskId)"
              >
                <span class="table-mark">▦</span>
                <span><strong>{{ table.title }}</strong><small>{{ table.rowCount }} 行 · {{ table.query }}</small></span>
                <em>⋮⋮</em>
                <span class="result-name-tooltip" role="tooltip">
                  <strong>{{ table.title }}</strong>
                  <small>{{ table.rowCount }} 行 · {{ table.query }}</small>
                </span>
              </button>
              <button
                class="delete-result"
                :aria-label="`删除结果表${table.title}`"
                title="删除结果表"
                @click.stop="deleteSavedResult(table)"
              >×</button>
            </div>
          </div>
        </div>
      </section>
    </aside>

  </div>
</template>
