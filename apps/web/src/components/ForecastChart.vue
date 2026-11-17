<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { formatTime } from '../lib/presentation'
const props = defineProps<{ series: any[] }>()
const node = ref<HTMLDivElement>(); let chart: echarts.ECharts | undefined
function draw() {
  if (!chart) return
  const rows = props.series || []; const labels = rows.map(x => formatTime(String(x.time)))
  chart.setOption({ animation: false, tooltip: { trigger: 'axis' }, grid: [{ left: 62, right: 20, top: 72, height: 140 }, { left: 62, right: 20, top: 252, height: 62 }], legend: { top: 8, data: ['Розрахована вологість', 'Опади'] }, xAxis: [{ type: 'category', data: labels, boundaryGap: false, axisLabel: { show: false } }, { type: 'category', data: labels, gridIndex: 1, axisLabel: { show: true, rotate: 20, interval: 1, fontSize: 10 } }], yAxis: [{ type: 'value', name: 'Вологість, м³/м³' }, { type: 'value', name: 'Опади, мм/інтервал', gridIndex: 1 }], series: [{ name: 'Розрахована вологість', type: 'line', data: rows.map(x => x.moisture_p50 ?? x.moisture ?? null), smooth: false, symbolSize: 5, lineStyle: { color: '#195f65', width: 3 }, itemStyle: { color: '#195f65' } }, { name: 'Опади', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: rows.map(x => x.precipitation_mm ?? null), itemStyle: { color: '#719bb7' } }] }, true)
}
const resize = () => chart?.resize()
onMounted(() => { if (node.value) { chart = echarts.init(node.value); draw(); window.addEventListener('resize', resize) } })
watch(() => props.series, draw, { deep: true }); onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
</script><template><div ref="node" class="chart" role="img" aria-label="Розрахована траєкторія вологості ґрунту та опади"></div></template><style scoped>.chart{height:390px;width:100%}</style>
