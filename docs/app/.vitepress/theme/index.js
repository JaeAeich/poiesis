import DefaultTheme from "vitepress/theme-without-fonts";
import { inject } from "@vercel/analytics";
import Layout from "./Layout.vue";
import PoiesisHome from "./components/PoiesisHome.vue";
import DeployPage from "./components/DeployPage.vue";
import TaskFigure from "./components/TaskFigure.vue";
import PoiDiagram from "./components/PoiDiagram.vue";
import FlowDiagram from "./components/FlowDiagram.vue";
import Callout from "./components/Callout.vue";
import SwaggerViewer from "./components/SwaggerViewer.vue";
import "./styles/tokens.css";
import "./styles/poiesis.css";
import "./styles/docs.css";
import "./swagger.css";

// Vercel Analytics only in production builds, in the browser
if (process.env.NODE_ENV === "production" && typeof window !== "undefined") {
  inject();
}

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    // PoiesisHome and DeployPage double as page layouts (frontmatter `layout: PoiesisHome`)
    app.component("PoiesisHome", PoiesisHome);
    app.component("DeployPage", DeployPage);
    app.component("TaskFigure", TaskFigure);
    app.component("FlowDiagram", FlowDiagram);
    app.component("PoiDiagram", PoiDiagram);
    app.component("Callout", Callout);
    app.component("SwaggerViewer", SwaggerViewer);
  },
};
