<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const refill = ref<any>(null)
const faceEdits = ref<Record<number, number | null>>({})
const saving = ref<number | null>(null)
const error = ref('')

async function load() {
  rows.value = await api('/lanes')
  faceEdits.value = Object.fromEntries(rows.value.map((r: any) => [r.id, r.min_face || null]))
}
async function loadLatest() {
  try { refill.value = await api('/refills/latest?location_id=1') } catch { /* */ }
}
onMounted(async () => {
  await load()
  try { refill.value = await api('/refills/run?location_id=1', { method: 'POST' }) } catch { /* */ }
})

function normFace(v: any): number | null {
  return v === null || v === undefined || v === '' ? null : Number(v)
}
function dirty(r: any) {
  return (normFace(faceEdits.value[r.id]) ?? 0) !== (r.min_face || 0)
}
function elevated(r: any) {
  return r.min_face > 0 && r.stock < r.min_face
}
function errMsg(e: any) {
  try { return JSON.parse(e.message).detail || e.message } catch { return e.message }
}
async function saveFace(r: any) {
  if (!dirty(r)) return
  error.value = ''
  saving.value = r.id
  try {
    await api('/lanes/' + r.id, {
      method: 'PATCH',
      body: JSON.stringify({ min_face: normFace(faceEdits.value[r.id]) }),
    })
    await load()       // 货道卡与最新单、汇总同数
    await loadLatest()
  } catch (e: any) {
    error.value = `货道 ${r.slot_no} 保存失败：${errMsg(e)}`
    await load()       // 三处不动，回显还原
  } finally {
    saving.value = null
  }
}
</script>
<template>
  <h1>货道格子</h1>
  <p class="sub">机面货道网格 · 格内库存条 · 陈列面可登记 · 右侧补货小票</p>
  <div v-if="error" class="vf-error">{{ error }}</div>
  <div class="vf-machine-layout">
    <div class="vf-slot-grid">
      <div v-for="r in rows" :key="r.id" class="vf-slot">
        <div class="vf-slot-no">{{ r.slot_no }}</div>
        <div class="vf-slot-sku">{{ r.sku_name }}</div>
        <div class="vf-slot-bar">
          <div
            class="vf-slot-fill"
            :class="{ 'vf-need': r.gap > 0 }"
            :style="{ width: Math.min(r.fill_pct, 100) + '%' }"
          />
        </div>
        <div class="vf-slot-meta">
          {{ r.stock }}/{{ r.capacity }} · 缺
          <b :class="{ 'vf-gap-up': elevated(r) }">{{ r.gap }}</b>
        </div>
        <div class="vf-slot-face">
          <span>陈列面</span>
          <input
            type="number"
            min="0"
            :max="r.capacity"
            placeholder="—"
            v-model.number="faceEdits[r.id]"
            @keyup.enter="saveFace(r)"
          />
          <button class="vf-face-save" :disabled="!dirty(r) || saving === r.id" @click="saveFace(r)">
            {{ saving === r.id ? '…' : '存' }}
          </button>
        </div>
      </div>
    </div>
    <aside class="vf-receipt" v-if="refill">
      <h2>*** 补货建议单 ***</h2>
      <div class="vf-receipt-line" v-for="l in refill.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}</span>
        <span>x{{ l.fill_qty }}</span>
      </div>
      <p class="muted" style="margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48;text-align:center">
        — 机面打印预览 —
      </p>
    </aside>
  </div>
</template>
