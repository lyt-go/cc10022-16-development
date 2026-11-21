import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type ConversionRow = {
  序号: number
  分区: string
  记录键: string
  字段: string
  参考类别: string
  原编码: string | number | null
  清洗后编码: string | number | null
  标准编码: string | null
  标准名称: string | null
  命中方式: string | null
  处理结果: string
  是否生效: boolean
  原因: string | null
  参考数据编号: string | null
  参考版本: string | null
  字典缺失: boolean
  规则编号: string
}

export type PartitionSummary = {
  分区: string
  明细行数: number
  转换为标准码: number
  已是标准码: number
  转换失败: number
  可生效编码: string[]
  涉及字段: string[]
  字典缺失类别: string[]
  字典缺失: boolean
}

export type ConversionResult = {
  ok: boolean
  reason?: string
  batch_id: number
  batch_no: string
  run_no: number
  entity_model?: string
  partition_field?: string
  rules?: { 规则ID: number; 规则编号: string; 字段: string; 参考类别: string; 字典缺失: boolean }[]
  total?: number
  detail_count?: number
  converted?: number
  failed?: number
  run_count?: number
  runs?: { 运行次数: number; 时间: string; 转换成功数: number; 转换失败数: number; 已是标准码?: number }[]
  partitions: PartitionSummary[]
  rows: ConversionRow[]
  formal_records: Record<string, unknown>[]
  all_already_standard?: boolean
  input_mode?: string
}

export type ConversionBatch = {
  id: number
  批次号: string
  运行次数: number
  实体模型: string
  分区字段: string
  记录键字段: string
  规则明细: { 规则ID: number; 规则编号: string; 字段: string; 参考类别: string; 字典缺失: boolean }[]
  总记录数: number
  明细行数: number
  转换成功数: number
  转换失败数: number
  分区: PartitionSummary[]
  状态: string
  创建时间: string
  运行记录: { 运行次数: number; 时间: string; 转换成功数: number; 转换失败数: number; 已是标准码?: number }[]
}

export type ConversionDelivery = {
  ok: boolean
  batch_no: string
  run_no: number
  entity_model: string
  partitions: {
    分区: string
    接收记录数: number
    可生效编码: string[]
    字典缺失: boolean
    records: Record<string, unknown>[]
    rejected: { 记录键: string; 字段: string; 参考类别: string; 原编码: unknown; 原因: string | null }[]
  }[]
}

export async function convertBatch(payload: {
  entity_model: string
  records: Record<string, unknown>[]
  rule_id?: number | null
  partition_field?: string
  record_key_field?: string
}): Promise<ConversionResult> {
  const response = await request('/api/field_cleanse/convert', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return (await response.json()) as ConversionResult
}

export async function listConversions(
  entityModel?: string,
): Promise<{ items: ConversionBatch[]; total: number }> {
  const query = entityModel ? `?entity_model=${encodeURIComponent(entityModel)}` : ''
  const response = await request(`/api/field_cleanse/conversions${query}`)
  if (!response.ok) throw new Error('转换批次读取失败')
  return await response.json()
}

export async function rerunConversion(
  batchId: number,
  inputMode: 'converted' | 'source' = 'converted',
): Promise<ConversionResult> {
  const response = await request(`/api/field_cleanse/conversions/${batchId}/rerun`, {
    method: 'POST',
    body: JSON.stringify({ input_mode: inputMode }),
  })
  return (await response.json()) as ConversionResult
}

export async function loadConversionDelivery(batchId: number): Promise<ConversionDelivery> {
  const response = await request(`/api/field_cleanse/conversions/${batchId}/delivery`)
  if (!response.ok) throw new Error('分区交付读取失败')
  return await response.json()
}

export async function loadConversionDetail(batchId: number): Promise<ConversionResult> {
  const response = await request(`/api/field_cleanse/conversions/${batchId}`)
  return (await response.json()) as ConversionResult
}
