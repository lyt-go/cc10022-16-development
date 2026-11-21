<template>
  <section class="page" data-testid="code-conversion">
    <header class="page-head">
      <div>
        <h2>参考类别标准码转换</h2>
        <p class="page-desc">
          字段标准化清洗规则按「参考类别」关联参考数据管理中的同名字典，批量转换逐行留痕，
          转换成功的记录按分区写入正式数据供报送系统接收。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/field_cleanse">返回清洗规则</RouterLink>
      </div>
    </header>

    <form class="analysis-form" @submit.prevent="submitConversion">
      <label>
        <span>实体模型</span>
        <input v-model="entityModel" data-testid="convert-entity" placeholder="如：客户主数据" required />
      </label>
      <label>
        <span>分区字段</span>
        <input v-model="partitionField" data-testid="convert-partition-field" placeholder="区域" />
      </label>
      <label>
        <span>记录键字段</span>
        <input v-model="recordKeyField" data-testid="convert-key-field" placeholder="记录编号" />
      </label>
      <button class="btn primary" data-testid="convert-submit" type="submit" :disabled="busy">
        {{ busy ? '转换中…' : '执行批量转换' }}
      </button>
      <button class="btn ghost" type="button" data-testid="convert-demo" @click="fillDemo">
        填入演示批次
      </button>
    </form>

    <label class="filter-item" style="display: block; margin-bottom: 12px">
      <span>原始记录（JSON 数组，每行一条）</span>
      <textarea
        v-model="recordsText"
        data-testid="convert-records"
        rows="8"
        style="width: 100%; font-family: monospace; font-size: 12px; padding: 8px; border: 1px solid var(--border); border-radius: 6px"
      />
    </label>

    <p v-if="errorMessage" class="error-text" data-testid="convert-error">{{ errorMessage }}</p>

    <article v-if="result" class="stat-row" data-testid="convert-summary">
      <div class="stat-card">
        <span class="stat-label">批次号</span>
        <strong class="stat-value" style="font-size: 13px">{{ result.batch_no }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">运行次数</span>
        <strong class="stat-value">{{ result.run_no }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">转换成功 / 失败</span>
        <strong class="stat-value">{{ result.converted }} / {{ result.failed }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">明细行数</span>
        <strong class="stat-value">{{ result.rows.length }}</strong>
      </div>
    </article>

    <template v-if="result">
      <h3 class="section-title">分区汇总</h3>
      <table class="data-table" data-testid="convert-partitions">
        <thead>
          <tr>
            <th>分区</th><th>明细行</th><th>转换为标准码</th><th>已是标准码</th>
            <th>转换失败</th><th>可生效编码</th><th>字典缺失类别</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in result.partitions" :key="item.分区">
            <td>{{ item.分区 }}</td>
            <td>{{ item.明细行数 }}</td>
            <td>{{ item.转换为标准码 }}</td>
            <td>{{ item.已是标准码 }}</td>
            <td :class="{ 'error-text': item.转换失败 }">{{ item.转换失败 }}</td>
            <td>{{ item.可生效编码.join('、') || '—' }}</td>
            <td>{{ item.字典缺失类别.join('、') || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">逐行标准码改写明细</h3>
      <table class="data-table" data-testid="convert-rows">
        <thead>
          <tr>
            <th>#</th><th>分区</th><th>记录键</th><th>字段</th><th>参考类别</th>
            <th>原编码</th><th>标准编码</th><th>标准名称</th><th>命中方式</th>
            <th>处理结果</th><th>原因</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in result.rows"
            :key="`${row.记录键}-${row.字段}-${row.序号}`"
            :data-testid="`convert-row-${row.记录键}-${row.字段}`"
            :data-result="row.处理结果"
          >
            <td>{{ row.序号 }}</td>
            <td>{{ row.分区 }}</td>
            <td>{{ row.记录键 }}</td>
            <td>{{ row.字段 }}</td>
            <td>{{ row.参考类别 }}</td>
            <td>{{ row.原编码 ?? '—' }}</td>
            <td>{{ row.标准编码 ?? '—' }}</td>
            <td>{{ row.标准名称 ?? '—' }}</td>
            <td>{{ matchLabel(row.命中方式) }}</td>
            <td :class="{ 'error-text': !row.是否生效 }">{{ resultLabel(row.处理结果) }}</td>
            <td>{{ row.原因 ?? '—' }}</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">正式数据（按分区接收）</h3>
      <table class="data-table" data-testid="convert-formal">
        <thead>
          <tr><th>分区</th><th>记录键</th><th>字段</th><th>参考类别</th><th>原编码</th><th>标准编码</th><th>参考数据编号</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in formalRowsView" :key="`${row.分区}-${row.记录键}-${row.字段}`">
            <td>{{ row.分区 }}</td>
            <td>{{ row.记录键 }}</td>
            <td>{{ row.字段 }}</td>
            <td>{{ row.参考类别 }}</td>
            <td>{{ row.原编码 ?? '—' }}</td>
            <td>{{ row.标准编码 }}</td>
            <td>{{ row.参考数据编号 ?? '—' }}</td>
          </tr>
          <tr v-if="!formalRowsView.length">
            <td colspan="7" class="empty-state">本批次没有可生效的正式数据</td>
          </tr>
        </tbody>
      </table>

      <div class="page-actions" style="margin-top: 12px">
        <button class="btn" type="button" data-testid="convert-rerun" :disabled="busy" @click="rerun">
          原批次再操作一次
        </button>
        <button class="btn" type="button" data-testid="convert-delivery" :disabled="busy" @click="loadDelivery">
          查看分区交付
        </button>
      </div>
      <p v-if="rerunHint" data-testid="convert-rerun-hint" class="page-desc">{{ rerunHint }}</p>

      <template v-if="delivery">
        <h3 class="section-title">报送系统分区交付</h3>
        <table class="data-table" data-testid="convert-delivery-table">
          <thead>
            <tr><th>分区</th><th>接收记录数</th><th>可生效编码</th><th>字典缺失</th><th>拒收行</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in delivery.partitions" :key="item.分区">
              <td>{{ item.分区 }}</td>
              <td>{{ item.接收记录数 }}</td>
              <td>{{ item.可生效编码.join('、') || '—' }}</td>
              <td>{{ item.字典缺失 ? '是' : '否' }}</td>
              <td>
                <span v-for="row in item.rejected" :key="`${row.记录键}-${row.字段}`">
                  {{ row.记录键 }}/{{ row.字段 }}（{{ row.原因 }}）
                </span>
                <span v-if="!item.rejected.length">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </template>

    <h3 class="section-title">转换批次</h3>
    <table class="data-table" data-testid="convert-batch-list">
      <thead>
        <tr>
          <th>批次号</th><th>实体模型</th><th>运行次数</th><th>明细行数</th>
          <th>成功</th><th>失败</th><th>状态</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="batch in batches" :key="batch.id">
          <td>{{ batch.批次号 }}</td>
          <td>{{ batch.实体模型 }}</td>
          <td>{{ batch.运行次数 }}</td>
          <td>{{ batch.明细行数 }}</td>
          <td>{{ batch.转换成功数 }}</td>
          <td>{{ batch.转换失败数 }}</td>
          <td>{{ batch.状态 }}</td>
          <td>
            <button class="link" type="button" :data-testid="`open-batch-${batch.id}`" @click="openBatch(batch.id)">
              查看明细
            </button>
          </td>
        </tr>
        <tr v-if="!batches.length">
          <td colspan="8" class="empty-state">暂无转换批次，可先执行一次批量转换</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  convertBatch,
  listConversions,
  loadConversionDelivery,
  loadConversionDetail,
  rerunConversion,
} from '@/api/backend-service'
import type { ConversionBatch, ConversionDelivery, ConversionResult } from '@/api/backend-service'

const entityModel = ref('客户主数据')
const partitionField = ref('区域')
const recordKeyField = ref('记录编号')
const recordsText = ref('')
const result = ref<ConversionResult | null>(null)
const batches = ref<ConversionBatch[]>([])
const delivery = ref<ConversionDelivery | null>(null)
const errorMessage = ref('')
const rerunHint = ref('')
const busy = ref(false)

const formalRowsView = computed(() => {
  const seen = new Set<string>()
  return (result.value?.formal_records ?? []).filter((row) => {
    const view = row as Record<string, string>
    const key = `${view['分区']}-${view['记录键']}-${view['字段']}-${view['参考类别']}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }) as Record<string, string>[]
})

const DEMO_RECORDS = [
  { 记录编号: 'E1', 区域: '东区', 城市: '北京', 卡种: '储蓄卡' },
  { 记录编号: 'E2', 区域: '东区', 城市: '火星', 卡种: '信用卡' },
  { 记录编号: 'W1', 区域: '西区', 城市: '上海', 卡种: '贷记卡' },
  { 记录编号: 'W2', 区域: '西区', 城市: '穗', 卡种: '储值卡' },
]

function fillDemo() {
  recordsText.value = JSON.stringify(DEMO_RECORDS, null, 2)
}

function matchLabel(value: string | null): string {
  return { standard: '标准码', alias: '别名', mapping: '映射关系' }[value ?? ''] ?? '—'
}

function resultLabel(value: string): string {
  return { converted: '已转换', already_standard: '已是标准码', missing: '失败', conflict: '歧义' }[value] ?? value
}

async function refreshBatches() {
  try {
    batches.value = (await listConversions(entityModel.value || undefined)).items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转换批次读取失败'
  }
}

async function submitConversion() {
  errorMessage.value = ''
  rerunHint.value = ''
  delivery.value = null
  let records: Record<string, unknown>[]
  try {
    records = JSON.parse(recordsText.value)
    if (!Array.isArray(records)) throw new Error('原始记录必须是 JSON 数组')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '原始记录不是合法 JSON'
    return
  }
  busy.value = true
  try {
    const payload = await convertBatch({
      entity_model: entityModel.value.trim(),
      records,
      partition_field: partitionField.value.trim() || '区域',
      record_key_field: recordKeyField.value.trim() || '记录编号',
    })
    if (!payload.ok) throw new Error(payload.reason ?? '转换失败')
    result.value = payload
    await refreshBatches()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转换失败'
  } finally {
    busy.value = false
  }
}

async function openBatch(batchId: number) {
  errorMessage.value = ''
  rerunHint.value = ''
  delivery.value = null
  const batch = batches.value.find((item) => item.id === batchId)
  if (batch) entityModel.value = batch.实体模型
  const payload = await loadConversionDetail(batchId)
  if (!payload.ok) {
    errorMessage.value = payload.reason ?? '明细读取失败'
    return
  }
  result.value = payload
}

async function rerun() {
  if (!result.value) return
  errorMessage.value = ''
  busy.value = true
  try {
    const payload = await rerunConversion(result.value.batch_id)
    if (!payload.ok) throw new Error(payload.reason ?? '重跑失败')
    result.value = payload
    rerunHint.value = payload.all_already_standard
      ? `第 ${payload.run_no} 次运行：已转换的新码全部按标准码命中，未再按旧别名改写。`
      : `第 ${payload.run_no} 次运行完成，仍有 ${payload.failed} 行未转换成功，请检查字典。`
    await refreshBatches()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重跑失败'
  } finally {
    busy.value = false
  }
}

async function loadDelivery() {
  if (!result.value) return
  errorMessage.value = ''
  try {
    delivery.value = await loadConversionDelivery(result.value.batch_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分区交付读取失败'
  }
}

onMounted(() => {
  fillDemo()
  void refreshBatches()
})
</script>
