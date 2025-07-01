/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { routeToUrl } from "@web/core/browser/router_service";
import { loadJS } from "@web/core/assets";

class SaccoDashboard extends Component {

    setup(){
        this.state = useState({
            dashboardData: {
                pie_chart_data: [],
                line_graph_data: [],
                total_loans_dispersed: 0,
                total_loans_paid_back: 0,
                total_deposits: 0,
            },
            period: 90,
        });
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.router = useService("router");

        // Create refs for the chart canvases
        this.pieChartRef = useRef("pieChart");
        this.lineChartRef = useRef("lineChart");

         // Check for old Chart.js and redirect if necessary
         console.log("Before old_chartjs")
         const old_chartjs = document.querySelector('script[src="/web/static/lib/Chart/Chart.js"]');
         if (old_chartjs) {
             let { search, hash } = this.router.current;
             search.old_chartjs = old_chartjs != null ? "0" : "1";
             hash.action = 86; // Adjust this action number if needed
             browser.location.href = browser.location.origin + routeToUrl(this.router.current);
         }
 
         onWillStart(async () => {
             // Load Moment.js and Chart.js
             await this.loadExternalLibraries();

             console.log("Before fetchDashboardData")
             await this.fetchDashboardData();
         });

        onMounted(() => {
            console.log("Pie chart element:", this.pieChartRef.el);
            console.log("Line chart element:", this.lineChartRef.el);
            this.renderCharts();
        })
    }

    async loadExternalLibraries() {
        const libraries = [
            "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.30.1/moment.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js",
            "https://cdn.jsdelivr.net/npm/chartjs-adapter-moment@1.0.0/dist/chartjs-adapter-moment.min.js"
        ];

        for (const lib of libraries) {
            try {
                await loadJS(lib);
            } catch (error) {
                console.error(`Failed to load ${lib}:`, error);
                throw new Error(`Failed to load required library: ${lib}`);
            }
        }
    }

    async fetchDashboardData(start_date, end_date) {
        try {
          const result = await this.orm.call(
            "sacco.dashboard",
            "get_dashboard_data",
            [start_date, end_date]
          );
          this.state.dashboardData = result;
          console.log("Dashboard data fetched:", this.state.dashboardData);
        } catch (error) {
          console.error('Error fetching dashboard data:', error);
        }
    }

    renderCharts() {
        console.log("Inside Rendering charts")
        try{

        const pieChartEl = this.pieChartRef.el;
        const lineChartEl = this.lineChartRef.el;
        

        if (pieChartEl && lineChartEl) {
            const pieChartCtx = pieChartEl.getContext('2d');
            const lineChartCtx = lineChartEl.getContext('2d');        

            // Destroy existing chart instances if they exist
            if (this.pieChart) {
                this.pieChart.destroy();
            }
            if (this.lineChart) {
                this.lineChart.destroy();
            }

            // Pie Chart
            // const pieChartCtx = this.el.querySelector('#loan_status_pie_chart').getContext('2d');
            console.log("Pie chart data:", this.state.dashboardData.pie_chart_data);
            this.pieChart = new Chart(pieChartCtx, {
                type: 'pie',
                data: {
                    labels: this.state.dashboardData.pie_chart_data.map(item => item.label),
                    datasets: [{
                        data: this.state.dashboardData.pie_chart_data.map(item => item.value),
                        backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF'],
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'top',
                        },
                        title: {
                            display: true,
                            text: 'Loan Status Distribution'
                        }
                    }
                }
            });

            // Line Chart
            // const lineChartCtx = this.el.querySelector('#loan_deposits_line_graph').getContext('2d');
            this.lineChart = new Chart(lineChartCtx, {
                type: 'line',
                data: {
                    labels: this.state.dashboardData.line_graph_data.map(item => moment(item.date)),
                    datasets: [{
                        label: 'Loans',
                        data: this.state.dashboardData.line_graph_data.map(item => ({
                            x: moment(item.date),
                            y: item.loans
                        })),
                        borderColor: '#FF6384',
                        fill: false
                    }, {
                        label: 'Deposits',
                        data: this.state.dashboardData.line_graph_data.map(item => ({
                            x: moment(item.date),
                            y: item.deposits
                        })),
                        borderColor: '#36A2EB',
                        fill: false
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'top',
                        },
                        title: {
                            display: true,
                            text: 'Loans and Deposits Over Time'
                        }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'day'
                            }
                        },
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });


          } else {
            console.error('Chart elements not found in the DOM');
          }
        } catch(error){
            console.error('Error rendering charts: ', error);
        }

    }

    onDateFilterChange(ev) {
        const filter = ev.target.value;
        console.log("Date filter changed:", ev.target.value);
        const today = moment();
        let start_date, end_date;

        switch (filter) {
            case 'last_7_days':
                start_date = today.clone().subtract(7, 'days').format('YYYY-MM-DD');
                end_date = today.format('YYYY-MM-DD');
                break;
            case 'last_90_days':
                start_date = today.clone().subtract(90, 'days').format('YYYY-MM-DD');
                end_date = today.format('YYYY-MM-DD');
                break;
            case 'today':
                start_date = today.format('YYYY-MM-DD');
                end_date = today.format('YYYY-MM-DD');
                break;
            case 'custom':
                this.el.querySelector('.custom-date-range').classList.remove('d-none');
                return;
            default:
                start_date = false;
                end_date = false;
        }

        this.fetchDashboardData(start_date, end_date).then(() => this.renderCharts());
    }

    onApplyCustomFilter() {
        const start_date = this.el.querySelector('#custom_start_date').value;
        const end_date = this.el.querySelector('#custom_end_date').value;
        this.fetchDashboardData(start_date, end_date).then(() => this.renderCharts());
    }
}

SaccoDashboard.template = 'sacco_transactions_management.SaccoDashboardTemplate';

registry.category("actions").add("sacco_dashboard", SaccoDashboard);

export default SaccoDashboard;