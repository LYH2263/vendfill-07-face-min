<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const refill = ref<any>(null)
const drafts = ref<Record<number, string>>({})
const saving = ref<Record<number, boolean>>({})

async function refresh() {
  rows.value = await api('/lanes?location_id=1')
  // 最新补货单：不存在时后端按当前有效缺口补建，保证货道卡 / 最新单 / 汇总同数
  refill.value = await api('/refills/latest?location_id=1')
  rows.value.forEach(r => { drafts.value[r.id] = r.min_facing ? String(r.min_facing) : '' })
}

function errText(e: unknown): string {
  const raw = (e as Error)?.message || '保存失败'
  try { return JSON.parse(raw).detail ?? raw } catch { return raw }
}

async function saveFacing(r: any) {
  const raw = (drafts.value[r.id] ?? '').trim()
  const facing = raw === '' ? 0 : Number(raw)
  if (!Number.isInteger(facing) || facing < 0) {
    alert('最低陈列面须为不小于 0 的整数（留空等同 0）')
    drafts.value[r.id] = r.min_facing ? String(r.min_facing) : ''
    return
  }
  saving.value[r.id] = true
  try {
    const res = await api(`/lanes/${r.id}`, {
      method: 'PUT', body: JSON.stringify({ min_facing: facing }),
    })
    Object.assign(r, res.lane)
    // 成功：重读最新单与汇总，三处按同一有效缺口出数
    refill.value = await api('/refills/latest?location_id=1')
  } catch (e) {
    // 失败：陈列面与单全回改前
    alert(errText(e))
    drafts.value[r.id] = r.min_facing ? String(r.min_facing) : ''
  } finally {
    saving.value[r.id] = false
  }
}

onMounted(refresh)
</script>
<template>
  <h1>货道格子</h1>
  <p class="sub">机面货道网格 · 格内登记最低陈列面 · 右侧最新补货小票</p>
  <div class="vf-summary-bar" v-if="refill">
    <span>建议补货总量 <b>{{ refill.total_fill }}</b></span>
    <span>待补 <b>{{ refill.need_fill_count }}</b></span>
    <span>满仓 <b>{{ refill.full_count }}</b></span>
    <span>超占 <b>{{ refill.overbooked_count }}</b></span>
  </div>
  <div class="vf-machine-layout">
    <div class="vf-slot-grid">
      <div v-for="r in rows" :key="r.id" class="vf-slot" :class="`vf-slot-${r.status}`">
        <div class="vf-slot-no">{{ r.slot_no }}</div>
        <div class="vf-slot-sku">{{ r.sku_name }}</div>
        <div class="vf-slot-bar">
          <div
            class="vf-slot-fill"
            :class="{ 'vf-need': r.status === 'need_fill' }"
            :style="{ width: Math.min(r.fill_pct, 100) + '%' }"
          />
        </div>
        <div class="vf-slot-meta">
          {{ r.stock }}/{{ r.capacity }} · 有效缺 {{ r.gap }}
          <small v-if="r.min_facing">· 陈列面 {{ r.min_facing }}</small>
        </div>
        <div class="vf-slot-meta">{{ r.status === 'need_fill' ? '待补' : r.status === 'full' ? '满仓' : '超占' }}</div>
        <label class="vf-facing-edit">
          陈列面
          <input
            type="number" min="0" :max="r.capacity"
            v-model="drafts[r.id]"
            @keyup.enter="saveFacing(r)"
          />
          <button class="btn vf-facing-btn" :disabled="saving[r.id]" @click="saveFacing(r)">
            {{ saving[r.id] ? '…' : '保存' }}
          </button>
        </label>
      </div>
    </div>
    <aside class="vf-receipt" v-if="refill">
      <h2>*** 最新补货单 #{{ refill.id }} ***</h2>
      <div class="vf-receipt-line" v-for="l in refill.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}<small v-if="l.min_facing">（面{{ l.min_facing }}）</small></span>
        <span>x{{ l.fill_qty }} · 缺{{ l.gap }}</span>
      </div>
      <p class="muted" style="margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48;text-align:center">
        — 货道 / 最新单 / 汇总同口径 —
      </p>
    </aside>
  </div>
</template>
