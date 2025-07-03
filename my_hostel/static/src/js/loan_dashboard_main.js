/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class LoanDashboardMain extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        this.state = useState({
            total_disbursed: 0,
            expected_outstanding: 0,
            actual_outstanding: 0,
            loan_count: 0,
            error: null,
            loanDetails: [],

            members: [],
            loanProducts: [],
            selectedMember: '',
            selectedLoanProduct: '',
            isFiltered: false,
        });
        this.barChartRef = useRef('barChart');

        onWillStart(async () => {
            await this.loadExternalLibraries();
            await this.fetchFilterOptions();
            await this.fetchDashboardData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async loadExternalLibraries() {
        const libraries = [
            'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
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

    async fetchFilterOptions() {
        try {
            const options = await this.orm.call('loan.portfolio', 'get_filter_options', []);
            this.state.members = options.members || [];
            this.state.loanProducts = options.loan_products || [];
        } catch (error) {
            console.error('Error fetching filter options:', error);
            this.state.error = 'Failed to fetch filter options: ' + error.message;
        }
    }

    async fetchDashboardData() {
        try {
            const hasFilters = this.state.selectedMember || this.state.selectedLoanProduct;
            
            if (hasFilters) {
                const data = await this.orm.call('loan.portfolio', 'get_filtered_metrics', [
                    this.state.selectedMember || null,
                    this.state.selectedLoanProduct || null
                ]);
                this.state.total_disbursed = data.total_disbursed || 0;
                this.state.expected_outstanding = data.expected_outstanding || 0;
                this.state.actual_outstanding = data.actual_outstanding || 0;
                this.state.loan_count = data.loan_count || 0;
                this.state.loanDetails = data.loan_details || [];
                this.state.isFiltered = true;
            } else {
                const data = await this.orm.call('loan.portfolio', 'get_overview_metrics', []);
                this.state.total_disbursed = data.total_disbursed || 0;
                this.state.expected_outstanding = data.expected_outstanding || 0;
                this.state.actual_outstanding = data.actual_outstanding || 0;
                this.state.loan_count = data.loan_count || 0;
                this.state.isFiltered = false;
                
                await this.fetchLoanDetails();
            }
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            this.state.error = 'Failed to fetch data: ' + error.message;
        }
    }

    async fetchLoanDetails() {
        try {
            const loans = await this.orm.searchRead('loan.details', [], [
                'loan_id',
                'member',
                'loan_product',
                'interest_rate',
                'disbursed_amount',
                'expected_outstanding',
                'actual_outstanding',
                'start_date',
            ]);
            this.state.loanDetails = loans;
        } catch (error) {
            console.error('Error fetching loan details:', error);
            this.state.error = 'Failed to fetch loan details: ' + error.message;
        }
    }

    async onMemberFilterChange(event) {
        this.state.selectedMember = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onLoanProductFilterChange(event) {
        this.state.selectedLoanProduct = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async clearFilters() {
        this.state.selectedMember = '';
        this.state.selectedLoanProduct = '';
        await this.fetchDashboardData();
        this.renderCharts();
    }

    renderCharts() {
        if (this.barChartRef.el) {
            const barCtx = this.barChartRef.el.getContext('2d');
            if (this.state.barChart) this.state.barChart.destroy();
            this.state.barChart = new Chart(barCtx, {
                type: 'bar',
                data: {
                    labels: ['Expected Outstanding', 'Actual Outstanding'],
                    datasets: [{
                        label: 'Amount (UGX)',
                        data: [
                            this.state.expected_outstanding,
                            this.state.actual_outstanding,
                        ],
                        backgroundColor: ['#FF6384', '#36A2EB'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { position: 'top' } },
                    layout: { padding: 10 },
                    height: 150,
                    width: 300,
                },
            });
        } else {
            console.error('Bar chart element not found');
        }
    }

    downloadReport() {
        try {
      
            const memberFilter = this.state.selectedMember || null;
            const loanProductFilter = this.state.selectedLoanProduct || null;
            
            this.orm.call('loan.portfolio', 'generate_pdf_report', [
                memberFilter, 
                loanProductFilter
            ]).then(action => {
                if (action) {
                    this.action.doAction(action);
                }
            }).catch(error => {
                console.error('Download Error:', error);
                this.state.error = 'Failed to generate PDF report: ' + error.message;
            });
        } catch (error) {
            console.error('Download failed:', error);
            this.state.error = 'Failed to download report: ' + error.message;
        }
    }
}

LoanDashboardMain.template = 'my_hostel.LoanDashboardMainTemplate';

registry.category('actions').add('loan_dashboard_main', LoanDashboardMain);