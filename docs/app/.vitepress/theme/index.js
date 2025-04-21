import DefaultTheme from 'vitepress/theme-without-fonts';
import SwaggerViewer from './components/SwaggerViewer.vue';
import { inject } from '@vercel/analytics'
import "@catppuccin/vitepress/theme/frappe/blue.css";
import "./custom.css";
import "./swagger.css";
import "./custom-fonts.css";

// Inject Vercel Analytics only in production and on the client-side
if (process.env.NODE_ENV === 'production' && typeof window !== 'undefined') {
    inject();
  }

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    // Register SwaggerViewer component globally
    app.component('SwaggerViewer', SwaggerViewer);
  },
};
