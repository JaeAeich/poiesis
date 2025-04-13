import DefaultTheme from 'vitepress/theme-without-fonts';
import SwaggerViewer from './components/SwaggerViewer.vue';
import "@catppuccin/vitepress/theme/frappe/blue.css";

import "./swagger.css";
import "./custom-fonts.css";

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    // Register SwaggerViewer component globally
    app.component('SwaggerViewer', SwaggerViewer);
  },
};
