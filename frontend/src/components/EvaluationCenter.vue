<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { api } from "../api"
import type { EvaluationCaseResult, EvaluationReport, EvaluationReportSummary } from "../types"

const reports = ref<EvaluationReportSummary[]>([])
const selectedId = ref("")
const report = ref<EvaluationReport | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const error = ref("")
const expandedCase = ref("")
const resultKey = (item: EvaluationCaseResult) => `${item.id}-${item.attempt ?? 1}`
const statusFilter = ref<"all" | "failed">("all")
const dateFilter = ref("all")

const capabilityMetrics = computed(() => {
  if (!report.value) return []
  const summary = report.value.summary
  return [
    ["明确查询准确率", summary.query_accuracy, "明确业务问题的最终结果"],
    ["澄清正确率", summary.clarification_accuracy, "缺少口径时正确询问"],
    ["多轮任务完成率", summary.multiturn_completion_rate, "补充信息后完成查询"],
    ["安全拦截通过率", summary.safety_pass_rate, "危险写操作未被执行"],
    ["权限隔离通过率", summary.permission_pass_rate, "越权数据未被访问"],
  ].filter((item) => item[1] !== null && item[1] !== undefined) as [string, number, string][]
})

const reportDates = computed(() => [...new Set(
  reports.value.map((item) => reportDate(item.evaluated_at)),
)])

const visibleReports = computed(() => dateFilter.value === "all"
  ? reports.value
  : reports.value.filter((item) => reportDate(item.evaluated_at) === dateFilter.value))

const filteredResults = computed(() => {
  const results = report.value?.results ?? []
  return statusFilter.value === "failed"
    ? results.filter((item) => !item.result_match)
    : results
})

function percent(value?: number) {
  return `${Math.round((value ?? 0) * 1000) / 10}%`
}

function formatTime(value?: string) {
  if (!value) return "未知时间"
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).format(new Date(value))
}

function reportDate(value?: string) {
  if (!value) return "未知日期"
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(value))
}

async function changeDateFilter(value: string) {
  dateFilter.value = value
  const candidates = visibleReports.value
  const preferred = candidates.find((item) => item.is_full) ?? candidates[0]
  if (preferred && preferred.id !== selectedId.value) await loadReport(preferred.id)
}

function caseStatus(item: EvaluationCaseResult) {
  if (item.result_match) return "通过"
  if (item.status === "waiting_clarification") return "需要澄清"
  if (!item.execution_success) return "执行失败"
  return "结果错误"
}

async function loadReport(id: string) {
  if (!id || detailLoading.value) return
  selectedId.value = id
  detailLoading.value = true
  error.value = ""
  expandedCase.value = ""
  try {
    report.value = await api.evaluationReport(id)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "评测报告加载失败"
  } finally {
    detailLoading.value = false
  }
}

onMounted(async () => {
  try {
    reports.value = await api.evaluationReports()
    const preferred = reports.value.find((item) => item.is_full) ?? reports.value[0]
    if (preferred) await loadReport(preferred.id)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "评测报告加载失败"
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="evaluation-center">
    <header class="evaluation-header">
      <div>
        <p class="kicker">AI QUALITY CONTROL</p>
        <h1>评测中心</h1>
        <p>查看模型问数质量与回归结果。评测任务仍由开发环境发起，页面仅提供只读分析。</p>
      </div>
      <div class="report-picker">
        <label>
          <span>评测日期</span>
          <select :value="dateFilter" :disabled="loading || detailLoading" @change="changeDateFilter(($event.target as HTMLSelectElement).value)">
            <option value="all">全部日期</option>
            <option v-for="date in reportDates" :key="date" :value="date">{{ date }}</option>
          </select>
        </label>
        <label>
          <span>评测批次</span>
          <select :value="selectedId" :disabled="loading || detailLoading" @change="loadReport(($event.target as HTMLSelectElement).value)">
            <option v-for="item in visibleReports" :key="item.id" :value="item.id">
              {{ formatTime(item.evaluated_at) }} · {{ item.case_count }} 条{{ item.is_full ? " · 全量" : " · 调试" }}
            </option>
          </select>
        </label>
      </div>
    </header>

    <div v-if="loading" class="evaluation-state"><span></span><p>正在读取评测报告…</p></div>
    <div v-else-if="error" class="evaluation-error">{{ error }}</div>
    <div v-else-if="!report" class="evaluation-empty">
      <strong>暂无评测报告</strong>
      <p>请先在后端运行评测脚本，完成后报告会自动出现在这里。</p>
    </div>

    <template v-else>
      <section class="evaluation-summary">
        <article class="metric-card primary">
          <small>结果准确率</small>
          <strong>{{ percent(report.summary.result_accuracy) }}</strong>
          <span>{{ Math.round(report.summary.result_accuracy * report.summary.run_count) }}/{{ report.summary.run_count }} 次结果正确</span>
        </article>
        <article class="metric-card">
          <small>SQL 执行成功率</small>
          <strong>{{ report.summary.sql_execution_success_rate === null ? "不适用" : percent(report.summary.sql_execution_success_rate) }}</strong>
          <span v-if="report.summary.sql_expected_run_count !== undefined">
            {{ report.summary.sql_execution_success_count }}/{{ report.summary.sql_expected_run_count }} 次应执行查询成功
          </span>
          <span v-else>生成并成功执行查询</span>
        </article>
        <article class="metric-card">
          <small>结果说明安全率</small>
          <strong>{{ percent(report.summary.displayed_summary_safety_rate) }}</strong>
          <span>说明与标准结果一致</span>
        </article>
        <article class="metric-card">
          <small>平均响应时间</small>
          <strong>{{ report.summary.average_latency_seconds.toFixed(1) }}s</strong>
          <span>P95 {{ report.summary.p95_latency_seconds.toFixed(1) }}s</span>
        </article>
      </section>

      <section v-if="capabilityMetrics.length" class="evaluation-summary capability-summary">
        <article v-for="item in capabilityMetrics" :key="item[0]" class="metric-card">
          <small>{{ item[0] }}</small>
          <strong>{{ percent(item[1]) }}</strong>
          <span>{{ item[2] }}</span>
        </article>
      </section>

      <section class="evaluation-panel">
        <div class="evaluation-panel-head">
          <div>
            <h2>用例明细</h2>
            <p>{{ report.summary.dataset }} · {{ report.summary.case_count }} 条用例 · 每题 {{ report.config.repeat }} 次</p>
          </div>
          <div class="evaluation-filters">
            <button :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'">全部 {{ report.results.length }}</button>
            <button :class="{ active: statusFilter === 'failed' }" @click="statusFilter = 'failed'">未通过 {{ report.results.filter(item => !item.result_match).length }}</button>
          </div>
        </div>

        <div class="evaluation-table-wrap">
          <table class="evaluation-table">
            <thead><tr><th>用例</th><th>轮次</th><th>业务分类</th><th>问题</th><th>状态</th><th>表/字段召回</th><th>耗时</th><th></th></tr></thead>
            <tbody>
              <template v-for="item in filteredResults" :key="resultKey(item)">
                <tr :class="{ failed: !item.result_match }">
                  <td><code>{{ item.id }}</code></td>
                  <td>第 {{ item.attempt ?? 1 }} 轮</td>
                  <td>{{ item.category }}</td>
                  <td class="case-question">{{ item.question }}</td>
                  <td><span class="case-status" :class="item.result_match ? 'passed' : 'failed'">{{ caseStatus(item) }}</span></td>
                  <td>{{ percent(item.table_recall) }} / {{ percent(item.field_recall) }}</td>
                  <td>{{ item.latency_seconds.toFixed(1) }}s</td>
                  <td><button class="case-expand" @click="expandedCase = expandedCase === resultKey(item) ? '' : resultKey(item)">{{ expandedCase === resultKey(item) ? "收起" : "详情" }}</button></td>
                </tr>
                <tr v-if="expandedCase === resultKey(item)" class="case-detail-row">
                  <td colspan="8">
                    <div class="case-detail">
                      <div><small>结果行数</small><strong>{{ item.actual_row_count ?? 0 }} / 标准 {{ item.expected_row_count ?? 0 }}</strong></div>
                      <div><small>失败归因</small><strong>{{ item.failure_reason || "无" }}</strong></div>
                      <div class="case-detail-wide"><small>结果说明</small><p>{{ item.detail || "暂无" }}</p></div>
                      <div v-if="item.clarification" class="case-detail-wide">
                        <small>实际澄清</small>
                        <p>{{ item.clarification.question }}</p>
                        <p>选项：{{ item.clarification.options.map(option => option.label).join("、") }}</p>
                      </div>
                      <div class="case-detail-wide"><small>生成 SQL</small><pre><code>{{ item.sql || "未生成 SQL" }}</code></pre></div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </main>
</template>
