import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("Uncaught error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center bg-paper-50 px-8 font-sans">
          <div className="max-w-md rounded-card border border-danger-600/40 bg-white p-6 text-center">
            <h1 className="font-serif text-xl text-ink-900">出错了</h1>
            <p className="mt-2 text-sm text-ink-600">
              应用遇到了一个意外错误，请尝试刷新页面。
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700"
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
