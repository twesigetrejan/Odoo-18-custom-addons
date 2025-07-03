/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class SavingsDashboardMain extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        this.state = useState({
            // Unfiltered metrics (total database)
            total_accounts: 0,
            total_balances: 0,
            
            // Filtered metrics
            filtered_accounts: 0,
            filtered_dormant_accounts: 0,
            filtered_dormant_balances: 0,
            filtered_dormant_percentage: 0,
            
            error: null,
            accountDetails: [],
            filteredAccountDetails: [],
            currentPage: 1,
            itemsPerPage: 10,
            totalPages: 1,

            // Filter options
            members: [],
            productTypes: [],
            portfolios: [],
            
            // Filter values with new defaults
            selectedMember: '',
            selectedProduct: '',
            selectedPortfolio: '',
            dormancyPeriod: 1, // 1 day default
            balanceThreshold: 10000, // UGX 10,000 default
            
            isFiltered: false,
        });
        
        this.barChartRef = useRef('barChart');
        this.pieChartRef = useRef('pieChart');
        this.balanceProductChartRef = useRef('balanceProductChart');

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
                this.state.error = `Failed to load required library: ${lib}`;
            }
        }
    }

    async fetchFilterOptions() {
        try {
            const options = await this.orm.call('saving.portfolio', 'get_filter_options', []);
            this.state.members = options.members || [];
            this.state.productTypes = options.product_types || [];
            this.state.portfolios = options.portfolios || [];
        } catch (error) {
            console.error('Error fetching filter options:', error);
            this.state.error = 'Failed to fetch filter options: ' + error.message;
        }
    }

    async fetchDashboardData() {
        try {
            const data = await this.orm.call('saving.portfolio', 'get_filtered_metrics', [
                this.state.selectedMember || null,
                this.state.selectedProduct || null,
                this.state.selectedPortfolio || null,
                this.state.dormancyPeriod,
                this.state.balanceThreshold
            ]);
            
            this.state.total_accounts = data.total_accounts || 0;
            this.state.total_balances = data.total_balances || 0;
            this.state.filtered_accounts = data.filtered_accounts || 0;
            this.state.filtered_dormant_accounts = data.filtered_dormant_accounts || 0;
            this.state.filtered_dormant_balances = data.filtered_dormant_balances || 0;
            this.state.filtered_dormant_percentage = data.filtered_dormant_percentage || 0;
            this.state.accountDetails = data.account_details || [];
            
            this.applyFiltersToAccounts();
            this.state.isFiltered = this.state.selectedMember || this.state.selectedProduct || 
                                 this.state.selectedPortfolio || this.state.dormancyPeriod !== 1 || 
                                 this.state.balanceThreshold !== 10000;
            
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            this.state.error = 'Failed to fetch data: ' + error.message;
        }
    }

    applyFiltersToAccounts() {
        this.state.filteredAccountDetails = this.state.accountDetails.filter(account => {
            const isDormant = account.days_idle >= this.state.dormancyPeriod;
            const meetsBalanceThreshold = account.balance >= this.state.balanceThreshold;
            const productMatch = this.state.selectedProduct ? 
                account.product_type === this.state.selectedProduct : true;
            const portfolioMatch = this.state.selectedPortfolio ? 
                account.portfolio_id[1] === this.state.selectedPortfolio : true;
            const memberMatch = this.state.selectedMember ? 
                account.member_name === this.state.selectedMember : true;
            
            return isDormant && meetsBalanceThreshold && productMatch && portfolioMatch && memberMatch;
        });
        
        this.state.currentPage = 1;
        this.state.totalPages = Math.ceil(this.state.filteredAccountDetails.length / this.state.itemsPerPage);
    }

    get paginatedAccountDetails() {
        const start = (this.state.currentPage - 1) * this.state.itemsPerPage;
        const end = start + this.state.itemsPerPage;
        return this.state.filteredAccountDetails.slice(start, end);
    }

    nextPage() {
        if (this.state.currentPage < this.state.totalPages) {
            this.state.currentPage++;
        }
    }

    prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
        }
    }

    async onMemberFilterChange(event) {
        this.state.selectedMember = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onProductFilterChange(event) {
        this.state.selectedProduct = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onPortfolioFilterChange(event) {
        this.state.selectedPortfolio = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onDormancyPeriodChange(event) {
        this.state.dormancyPeriod = parseInt(event.target.value) || 1;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onBalanceThresholdChange(event) {
        this.state.balanceThreshold = parseInt(event.target.value) || 10000;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async clearFilters() {
        this.state.selectedMember = '';
        this.state.selectedProduct = '';
        this.state.selectedPortfolio = '';
        this.state.dormancyPeriod = 1;
        this.state.balanceThreshold = 10000;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    renderCharts() {
        this.renderBarChart();
        this.renderPieChart();
        this.renderBalanceProductChart();
    }

    renderBarChart() {
        if (this.barChartRef.el) {
            const ctx = this.barChartRef.el.getContext('2d');
            if (this.state.barChart) this.state.barChart.destroy();
            
            this.state.barChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['Total Accounts', 'Dormant Accounts', 'Above Threshold'],
                    datasets: [{
                        label: 'Count',
                        data: [
                            this.state.filtered_accounts,
                            this.state.filtered_dormant_accounts,
                            this.state.filtered_accounts - this.state.filtered_dormant_accounts
                        ],
                        backgroundColor: ['#36A2EB', '#FF6384', '#4BC0C0'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { display: false } },
                },
            });
        }
    }

    renderPieChart() {
        if (this.pieChartRef.el) {
            const ctx = this.pieChartRef.el.getContext('2d');
            if (this.state.pieChart) this.state.pieChart.destroy();
            
            this.state.pieChart = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: ['Active Accounts', 'Dormant Accounts'],
                    datasets: [{
                        data: [
                            this.state.filtered_accounts - this.state.filtered_dormant_accounts,
                            this.state.filtered_dormant_accounts
                        ],
                        backgroundColor: ['#36A2EB', '#FF6384'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom' } },
                },
            });
        }
    }

    renderBalanceProductChart() {
        if (this.balanceProductChartRef.el) {
            const ctx = this.balanceProductChartRef.el.getContext('2d');
            if (this.state.balanceProductChart) this.state.balanceProductChart.destroy();
            
            const productBalances = {};
            this.state.filteredAccountDetails.forEach(account => {
                const productType = account.product_type;
                productBalances[productType] = (productBalances[productType] || 0) + account.balance;
            });
            
            this.state.balanceProductChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: Object.keys(productBalances).map(this.getProductTypeDisplay),
                    datasets: [{
                        label: 'Total Balance',
                        data: Object.values(productBalances),
                        backgroundColor: '#36A2EB',
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { display: false } },
                },
            });
        }
    }

    downloadReport() {
        try {
            const memberFilter = this.state.selectedMember || null;
            const productFilter = this.state.selectedProduct || null;
            const portfolioFilter = this.state.selectedPortfolio || null;
            
            this.orm.call('saving.portfolio', 'generate_pdf_report', [
                memberFilter,
                productFilter,
                portfolioFilter,
                this.state.dormancyPeriod,
                this.state.balanceThreshold
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

    getProductTypeDisplay(value) {
        const productTypes = {
            'ordinary': 'Ordinary Savings',
            'fixed_deposit': 'Fixed Deposit',
            'premium': 'Premium Savings',
            'regular': 'Regular Savings',
            'youth': 'Youth Savings',
        };
        return productTypes[value] || value;
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-UG', {
            style: 'currency',
            currency: 'UGX',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        }).format(amount);
    }

    formatDate(dateString) {
        if (!dateString) return '';
        return new Date(dateString).toLocaleDateString('en-UG');
    }
}

SavingsDashboardMain.template = 'my_hostel.SavingsDashboardMainTemplate';
registry.category('actions').add('savings_dashboard_main', SavingsDashboardMain);