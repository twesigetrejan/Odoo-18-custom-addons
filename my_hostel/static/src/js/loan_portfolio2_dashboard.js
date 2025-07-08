/** @odoo-module **/

import { Component, onWillStart, useState } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';

export class LoanPortfolio2Dashboard extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        this.notification = useService('notification');


        
        // Set default dates
        const today = new Date();
        const firstDayOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        const lastDayOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        
        this.state = useState({
            dateFrom: firstDayOfMonth.toISOString().split('T')[0],
            dateTo: lastDayOfMonth.toISOString().split('T')[0],
            selectedProduct: '',
            selectedCurrency: '',
            currentPage: 1,
            
            portfolioData: [],
            totals: {
                total_opening: 0,
                total_disbursements: 0,
                total_principal_repaid: 0,
                total_interest_earned: 0,
                total_closing: 0,
                total_change_percentage: 0
            },
            
            productOptions: [
                { id: 'ordinary', name: 'Ordinary Savings' },
                { id: 'fixed_deposit', name: 'Fixed Deposit' },
                { id: 'premium', name: 'Premium Savings' },
                { id: 'regular', name: 'Regular Savings' },
                { id: 'youth', name: 'Youth Savings' }
            ],
            currencies: [],
            error: null,
            loading: false
        });

        onWillStart(async () => {
            await this.loadCurrencyOptions();
            await this.loadDashboardData();
        });
    }

    async loadCurrencyOptions() {
        try {
            const options = await this.orm.call('loan.portfolio2', 'get_filter_options', []);
            this.state.currencies = options.currencies || [];
            
            if (this.state.currencies.length > 0) {
                this.state.selectedCurrency = this.state.currencies[0].id;
            }
        } catch (error) {
            console.error('Failed to load currency options:', error);
            this.notification.add('Failed to load currency options', {
                type: 'danger',
            });
        }
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.error = null;
        
        try {
            const params = {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                product_type: this.state.selectedProduct || false
            };

            const result = await this.orm.call(
                'loan.portfolio2',
                'get_dashboard_data',
                [params.date_from, params.date_to, params.product_type]
            );

            if (!result) {
                throw new Error("No data returned from server");
            }

            // Transform data to include both product name and type
            this.state.portfolioData = Object.entries(result.product_data || {}).map(([product, data]) => ({
                product: product,
                product_type: data.product_type || '',
                opening_portfolio: data.opening_portfolio || 0,
                disbursements: data.disbursements || 0,
                principal_repaid: data.principal_repaid || 0,
                interest_earned: data.interest_earned || 0,
                closing_portfolio: data.closing_portfolio || 0,
                change_percentage: data.change_percentage || 0
            }));
            
            // Calculate totals
            this.state.totals = {
                total_opening: result.total_opening || 0,
                total_disbursements: result.total_disbursements || 0,
                total_principal_repaid: result.total_principal_repaid || 0,
                total_interest_earned: result.total_interest_earned || 0,
                total_closing: result.total_closing || 0,
                total_change_percentage: this.calculateTotalChangePercentage(
                    result.total_opening || 0, 
                    result.total_closing || 0
                )
            };
            
        } catch (error) {
            console.error('Failed to load dashboard data:', error);
            this.state.error = error.message || 'Failed to load dashboard data';
            this.notification.add(this.state.error, {
                type: 'danger',
            });
        } finally {
            this.state.loading = false;
        }
    }

    calculateTotalChangePercentage(opening, closing) {
        if (opening && opening !== 0) {
            return ((closing - opening) / opening) * 100;
        }
        return 0;
    }

    // Event handlers
    async onDateFromChange(event) {
        this.state.dateFrom = event.target.value;
    }

    async onDateToChange(event) {
        this.state.dateTo = event.target.value;
    }

    async onProductChange(event) {
        try {
            this.state.selectedProduct = event.target.value;
            await this.loadDashboardData();
        } catch (error) {
            console.error('Product change error:', error);
            this.state.error = 'Failed to change product filter';
            this.notification.add(this.state.error, { type: 'danger' });
        }
    }

    async onCurrencyChange(event) {
        this.state.selectedCurrency = event.target.value;
    }
    async onPageChange(page) {
        if (page >= 1 && page <= Math.ceil(this.state.portfolioData.length / 10)) {
            this.state.currentPage = page;
        }
    }

    async applyFilters() {
        await this.loadDashboardData();
    }

    // Utility methods
    formatCurrency(amount) {
        const currency = this.state.currencies.find(c => c.id === parseInt(this.state.selectedCurrency));
        const symbol = currency ? currency.symbol : '$';
        
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(amount).replace('$', symbol);
    }

    // Action methods
    async exportData() {
        try {
            const data = {
                portfolioData: this.state.portfolioData,
                totals: this.state.totals,
                filters: {
                    dateFrom: this.state.dateFrom,
                    dateTo: this.state.dateTo,
                    selectedProduct: this.state.selectedProduct,
                    selectedCurrency: this.state.selectedCurrency
                }
            };

            // Convert to CSV
            const csvContent = this.convertToCSV(data);
            
            // Create and download file
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            link.setAttribute('download', `loan_portfolio_${this.state.dateFrom}_to_${this.state.dateTo}.csv`);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
        } catch (error) {
            console.error('Export failed:', error);
            this.state.error = 'Export failed';
            this.notification.add(this.state.error, { type: 'danger' });
        }
    }

    convertToCSV(data) {
        const headers = ['Product Type', 'Product', 'Opening Portfolio', 'Disbursements', 
                       'Principal Repaid', 'Interest Earned', 'Closing Portfolio', 'Change %'];
        const csvRows = [headers.join(',')];
        
        // Add data rows
        data.portfolioData.forEach(item => {
            const row = [
                this.getProductTypeName(item.product_type),
                item.product,
                item.opening_portfolio,
                item.disbursements,
                item.principal_repaid,
                item.interest_earned,
                item.closing_portfolio,
                item.change_percentage.toFixed(2)
            ];
            csvRows.push(row.join(','));
        });
        
        // Add totals row
        const totalsRow = [
            'TOTALS',
            '',
            data.totals.total_opening,
            data.totals.total_disbursements,
            data.totals.total_principal_repaid,
            data.totals.total_interest_earned,
            data.totals.total_closing,
            data.totals.total_change_percentage.toFixed(2)
        ];
        csvRows.push(totalsRow.join(','));
        
        return csvRows.join('\n');
    }

    getProductTypeName(type) {
        const product = this.state.productOptions.find(p => p.id === type);
        return product ? product.name : type;
    }

    async downloadReport() {
        try {
            const params = {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                product_type: this.state.selectedProduct || null
            };

            const result = await this.orm.call('loan.portfolio2', 'generate_snapshot_report', [], params);
            
            if (result && result.type === 'ir.actions.report') {
                this.action.doAction(result);
            }
            
        } catch (error) {
            console.error('Report generation failed:', error);
            this.state.error = 'Report generation failed';
            this.notification.add(this.state.error, { type: 'danger' });
        }
    }
}

LoanPortfolio2Dashboard.template = 'my_hostel.LoanPortfolio2DashboardTemplate';
registry.category('actions').add('loan_portfolio2_dashboard', LoanPortfolio2Dashboard);