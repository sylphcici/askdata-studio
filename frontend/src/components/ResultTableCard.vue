<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { api } from "../api"

const props = withDefaults(defineProps<{
  title: string
  columns: string[]
  rows: Record<string, unknown>[]
  taskId: string
  totalRowCount?: number
  rowsTruncated?: boolean
  updatedAt?: string
  loading?: boolean
  error?: string
  initialPageSize?: number
}>(), {
  updatedAt: "刚刚更新",
  loading: false,
  error: "",
  initialPageSize: 10,
  totalRowCount: 0,
  rowsTruncated: false,
})

const page = ref(1)
const pageSize = ref(props.initialPageSize)
const exporting = ref(false)
const exportError = ref("")
const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / pageSize.value)))
const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return props.rows.slice(start, start + pageSize.value)
})

watch(() => props.rows, () => { page.value = 1 })
watch(pageSize, () => { page.value = 1 })

function previousPage() {
  page.value = Math.max(1, page.value - 1)
}

function nextPage() {
  page.value = Math.min(totalPages.value, page.value + 1)
}

function formatCell(value: unknown, column: string) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value !== "number") return String(value)
  if (/金额|销售额|客单价|收入/.test(column)) {
    return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(value)
  }
  if (/率|占比/.test(column)) return `${(value * 100).toFixed(1)}%`
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })
}

async function exportExcel() {
  if (!props.rows.length || exporting.value) return
  exporting.value = true
  exportError.value = ""
  try {
    const blob = await api.exportTask(props.taskId)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    const safeTitle = props.title.replace(/[\\/:*?"<>|]/g, "_")
    anchor.href = url
    anchor.download = `${safeTitle}_${new Date().toISOString().slice(0, 10)}.xls`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => {
      URL.revokeObjectURL(url)
    }, 1000)
  } catch (error) {
    exportError.value = error instanceof Error ? error.message : "导出失败"
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <section class="data-card" aria-label="表格查询结果">
    <header class="data-card-header">
      <div class="data-card-heading">
        <span class="sheet-icon">▦</span>
        <div><strong>{{ title }}</strong><small>{{ (totalRowCount || rows.length).toLocaleString("zh-CN") }} 行<span v-if="rowsTruncated"> · 当前预览 {{ rows.length }} 行</span> · {{ updatedAt }}</small></div>
      </div>
      <div class="data-card-actions">
        <slot name="actions"></slot>
        <button class="export-button" :class="{ disabled: !rows.length || exporting }" :disabled="!rows.length || exporting" @click="exportExcel">
          <span>⇩</span>{{ exporting ? "正在导出" : "导出 Excel" }}
        </button>
      </div>
    </header>

    <slot name="details"></slot>
    <p v-if="exportError" class="export-error">{{ exportError }}</p>

    <div v-if="loading" class="table-state"><span class="state-spinner"></span><strong>正在加载表格数据…</strong></div>
    <div v-else-if="error" class="table-state error"><span>!</span><strong>{{ error }}</strong></div>
    <div v-else-if="!rows.length" class="table-state"><span>○</span><strong>当前没有可展示的数据</strong><small>调整查询条件后再试一次</small></div>
    <template v-else>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th v-for="column in columns" :key="column">{{ column }}</th></tr></thead>
          <tbody>
            <tr v-for="(row, rowIndex) in pagedRows" :key="rowIndex">
              <td v-for="column in columns" :key="column" :title="String(row[column] ?? '')">{{ formatCell(row[column], column) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer class="data-card-footer">
        <label>每页
          <select v-model.number="pageSize" aria-label="每页显示数量"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select>
          行
        </label>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <div class="page-actions">
          <button :disabled="page === 1" aria-label="上一页" @click="previousPage">‹</button>
          <button :disabled="page === totalPages" aria-label="下一页" @click="nextPage">›</button>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.data-card { overflow: hidden; border: 1px solid #dfe7e2; border-radius: 15px; background: #fff; box-shadow: 0 12px 34px rgba(34, 68, 49, .08); }
.data-card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; padding: 13px 16px; border-bottom: 1px solid #e9eeea; background: linear-gradient(135deg, #fbfdfb, #f4f9f6); }
.data-card-heading, .data-card-actions { display: flex; align-items: center; gap: 10px; }.data-card-heading { min-width: 0; }
.sheet-icon { display: grid; place-items: center; width: 34px; height: 34px; flex: none; border-radius: 10px; color: #24714f; background: #e3f1e8; font-size: 14px; }
.data-card-heading strong, .data-card-heading small { display: block; }.data-card-heading strong { overflow: hidden; color: #28382f; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }.data-card-heading small { margin-top: 4px; color: #8a968f; font-size: 10px; }
.data-card-actions :deep(button), .export-button { min-height: 30px; padding: 0 10px; border: 1px solid #dce4df; border-radius: 8px; color: #5f6d65; background: #fff; font-size: 10px; }
.export-button { display: flex; align-items: center; gap: 5px; border-color: #246b4e; color: #fff; background: #246b4e; cursor: pointer; font-weight: 600; text-decoration: none; }.export-button span { font-size: 12px; }.export-button.disabled { cursor: default; opacity: .45; }
.export-error { margin: 0; padding: 8px 14px; color: #a45143; background: #fff5f3; font-size: 11px; }
.data-table-wrap { max-height: 430px; overflow: auto; }
.data-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
.data-table th { position: sticky; top: 0; z-index: 1; padding: 11px 14px; border-bottom: 1px solid #dfe6e1; color: #6e7b74; background: #f6f8f6; text-align: left; font-size: 10px; font-weight: 700; white-space: nowrap; }
.data-table td { max-width: 240px; padding: 11px 14px; overflow: hidden; border-bottom: 1px solid #edf0ee; color: #3f4b44; text-overflow: ellipsis; white-space: nowrap; }
.data-table tbody tr:nth-child(even) { background: #fbfcfb; }.data-table tbody tr:hover { background: #edf7f1; }
.data-card-footer { display: flex; align-items: center; min-height: 50px; gap: 16px; padding: 9px 14px; color: #7c8881; background: #fbfcfb; font-size: 10px; }
.data-card-footer label { display: flex; align-items: center; gap: 5px; }.data-card-footer select { padding: 4px 16px 4px 6px; border: 1px solid #dce3de; border-radius: 6px; color: #4e5e55; background: #fff; font-size: 10px; }
.data-card-footer > span { margin-left: auto; }.page-actions { display: flex; gap: 5px; }.page-actions button { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid #dbe3de; border-radius: 7px; color: #486057; background: #fff; font-size: 15px; }.page-actions button:disabled { opacity: .35; }
.table-state { display: flex; min-height: 180px; flex-direction: column; align-items: center; justify-content: center; gap: 7px; color: #87928c; }.table-state > span { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: #edf3ef; }.table-state strong { font-size: 12px; }.table-state small { font-size: 10px; }.table-state.error { color: #a45143; }
.state-spinner { border: 2px solid #dbe9e0; border-top-color: #277454; border-radius: 50% !important; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 620px) { .data-card-header { align-items: flex-start; flex-direction: column; }.data-card-actions { width: 100%; justify-content: flex-end; }.data-card-footer { gap: 8px; }.data-table td, .data-table th { padding: 10px; } }
</style>
