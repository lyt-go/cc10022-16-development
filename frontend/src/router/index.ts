import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import CodeConversionView from '@/views/CodeConversionView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/code_conversion', name: 'code_conversion', component: CodeConversionView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
