/** @odoo-module **/

import { Component, useState, onWillStart, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const numberFormatter = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
});

class TransactionsView extends Component {
    static template = "savings_management.TransactionsView";

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.user = useService("user"); // Add user service

        this.state = useState({
            memberId: null,
            memberName: "",
            memberMemberID: null,
            date: new Date().toISOString().split('T')[0],
            currencyId: null,
            receivingAccountId: null,
            amount: 0,
            transactions: [{ type: 'savings', productId: null, amount: 0 }],
            availableProducts: { savings: [], investments: [], loans: [], shares: [] },
            availableTypes: [],
            receivingAccounts: [],
            currencies: [],
            loading: false,
            memberSuggestions: [],
            lastTransactionSummary: null,
            isMemberRegistrar: false, // Add state for group checks
            isSaccoTeller: false,
            isSuperUser: false,
        });

        this.memberInput = useRef("memberInput");

        onWillStart(async () => {
            await this.loadInitialData();
            await this.loadAvailableTypes();
            // Check group membership
            this.state.isMemberRegistrar = await this.user.hasGroup('sacco_transactions_management.group_sacco_member_registrar');
            this.state.isSaccoTeller = await this.user.hasGroup('sacco_transactions_management.group_sacco_teller');
            this.state.isSuperUser = await this.user.hasGroup('sacco_transactions_management.group_sacco_super_user');
        });
    }

    async loadAvailableTypes() {
        const availableTypes = [];
        const modelsToCheck = {
            savings: 'savings.transaction',
            investments: 'sacco.investments.transaction',
            loans: 'sacco.loan.payments',
            shares: 'shares.transaction',
        };

        for (const [type, model] of Object.entries(modelsToCheck)) {
            try {
                await this.orm.search(model, [], { limit: 1 });
                availableTypes.push(type);
                console.log(`${type} module is available`);
            } catch (error) {
                console.log(`${model} is not available, skipping...`);
            }
        }
        this.state.availableTypes = availableTypes;

        if (this.state.availableTypes.length > 0) {
            this.state.transactions[0].type = this.state.availableTypes[0];
        } else {
            this.state.transactions = [];
            this.notification.add(_t("No transaction types available. Please install a module (Savings, Investments, Loans, or Shares)."), { type: "warning" });
        }
    }

    getTotalDistributed() {
        return this.state.transactions.reduce((sum, t) => sum + (t.amount || 0), 0);
    }

    isFormValid() {
        const totalDistributed = this.getTotalDistributed();
        return (
            this.state.memberId &&
            this.state.receivingAccountId &&
            totalDistributed === parseFloat(this.state.amount) &&
            this.state.transactions.some(t => t.amount > 0 && t.productId)
        );
    }

    formatAmount(amount) {
        return numberFormatter.format(amount || 0);
    }

    parseAmount(value) {
        if (!value) return 0;
        return parseFloat(value.replace(/,/g, '')) || 0;
    }

    async loadInitialData() {
        try {
            this.state.loading = true;
            const [receivingAccounts, currencies] = await Promise.all([
                this.orm.searchRead('sacco.receiving.account', [['status', '=', 'active']], ['name', 'account_id']),
                this.orm.searchRead('res.currency', [], ['name', 'id'])
            ]);
            this.state.receivingAccounts = receivingAccounts.map(acc => ({
                id: acc.id,
                name: acc.name,
                account_id: acc.account_id[0] || false
            }));
            this.state.currencies = currencies;
            this.state.currencyId = currencies.find(c => c.name === 'UGX')?.id || currencies[0]?.id;
        } catch (error) {
            console.error('Error loading initial data:', error);
            this.notification.add(_t("Error loading initial data"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async onMemberSearch(ev) {
        const searchTerm = ev.target.value;
        this.state.memberName = searchTerm;

        if (searchTerm.length < 2) {
            this.state.memberSuggestions = [];
            return;
        }

        try {
            this.state.loading = true;
            const members = await this.orm.searchRead(
                'res.partner',
                [['is_sacco_member', '=', true], '|', ['name', 'ilike', searchTerm], ['member_id', 'ilike', searchTerm]],
                ['name', 'id', 'member_id'],
                { limit: 10 }
            );
            this.state.memberSuggestions = members;
        } catch (error) {
            console.error('Error searching members:', error);
            this.notification.add(_t("Error searching members"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onMemberSelect(memberId, memberName, memberMemberID) {
        this.state.memberId = memberId;
        this.state.memberName = memberMemberID ? `${memberName} - ${memberMemberID}` : memberName;
        this.state.memberMemberID = memberMemberID;
        this.state.memberSuggestions = [];
        this.loadMemberProducts();
    }

    async loadMemberProducts() {
        if (!this.state.memberId) return;

        try {
            this.state.loading = true;
            const products = { savings: [], investments: [], loans: [], shares: [] };

            if (this.state.availableTypes.includes('savings')) {
                // Fetch all savings products (no active filter)
                products.savings = await this.orm.searchRead(
                    'sacco.savings.product',
                    [], // No domain filter
                    ['id', 'name', 'currency_id']
                );
            }

            if (this.state.availableTypes.includes('investments')) {
                // Fetch all investment products (no active filter)
                products.investments = await this.orm.searchRead(
                    'sacco.investments.product',
                    [], // No domain filter
                    ['id', 'name', 'currency_id']
                );
            }

            if (this.state.availableTypes.includes('loans')) {
                // Fetch all loan types (no active filter)
                const loanTypes = await this.orm.searchRead(
                    'sacco.loan.type',
                    [], // No domain filter
                    ['id', 'name', 'currency_id']
                );
                products.loans = loanTypes.map(lt => ({
                    id: lt.id,
                    name: lt.name,
                    currency_id: lt.currency_id,
                    loan_type_id: [lt.id, lt.name]
                }));
            }

            if (this.state.availableTypes.includes('shares')) {
                // Fetch all shares products (no active filter)
                products.shares = await this.orm.searchRead(
                    'sacco.shares.product',
                    [], // No domain filter
                    ['id', 'name', 'currency_id']
                );
            }

            this.state.availableProducts = products;

            if (this.state.availableTypes.length > 0) {
                this.state.transactions = [{ type: this.state.availableTypes[0], productId: null, amount: 0 }];
            }
        } catch (error) {
            console.error('Error loading member products:', error);
            this.notification.add(_t("Error loading member products"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onTypeChange(index, ev) {
        const type = ev.target.value;
        this.state.transactions[index].type = type;
        this.state.transactions[index].productId = null;
        this.state.transactions[index].amount = 0;
    }

    onAmountChange(index, ev) {
        const formattedValue = ev.target.value;
        const rawValue = this.parseAmount(formattedValue);
        this.state.transactions[index].amount = rawValue;
        ev.target.value = this.formatAmount(rawValue);
    }

    onTotalAmountChange(ev) {
        const formattedValue = ev.target.value;
        const rawValue = this.parseAmount(formattedValue);
        this.state.amount = rawValue;
        ev.target.value = this.formatAmount(rawValue);
    }

    addTransactionRow() {
        if (this.state.availableTypes.length > 0) {
            this.state.transactions.push({ type: this.state.availableTypes[0], productId: null, amount: 0 });
        }
    }

    removeTransactionRow(index) {
        if (this.state.transactions.length > 1) {
            this.state.transactions.splice(index, 1);
        } else {
            this.notification.add(_t("At least one transaction row is required"), { type: "warning" });
        }
    }

    validateForm() {
        const totalDistributed = this.getTotalDistributed();

        if (!this.state.memberId) {
            throw new Error(_t("Please select a member"));
        }
        if (!this.state.receivingAccountId) {
            throw new Error(_t("Please select a receiving account"));
        }
        if (totalDistributed !== parseFloat(this.state.amount)) {
            throw new Error(_t("Total distributed amount must match the total amount"));
        }
        if (!this.state.transactions.some(t => t.amount > 0 && t.productId)) {
            throw new Error(_t("Please specify at least one transaction with amount and product"));
        }

        const selectedCurrency = this.state.currencyId;
        for (const trans of this.state.transactions) {
            if (trans.amount > 0 && trans.productId) {
                const product = this.state.availableProducts[trans.type].find(p => p.id === trans.productId);
                if (product && product.currency_id && product.currency_id[0] !== selectedCurrency) {
                    throw new Error(_t("Currency mismatch between transaction and product"));
                }
            }
        }
    }

    async onPayClick() {
        try {
            const confirmed = await new Promise((resolve) => {
                this.dialog.add(ConfirmationDialog, {
                    title: _t("Confirm"),
                    body: _t("Are you sure you want to process these transactions? They will be set to Verified and require Approval."),
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                });
            });

            if (!confirmed) return;

            this.validateForm();
            this.state.loading = true;

            const memberId = Number.isInteger(this.state.memberId) ? this.state.memberId : parseInt(this.state.memberId, 10);
            if (!memberId || isNaN(memberId)) {
                throw new Error(_t("Invalid member ID: ") + this.state.memberId);
            }
            console.log("Member Id:", memberId);

            const generalTransactionData = {
                member_id: memberId,
                transaction_date: this.state.date,
                total_amount: this.state.amount,
                currency_id: this.state.currencyId,
                receiving_account_id: parseInt(this.state.receivingAccountId, 10),
                state: 'verified',
            };
            const rawGeneralTransactionId = await this.orm.create('sacco.general.transaction', [generalTransactionData]);
            let generalTransactionId = Array.isArray(rawGeneralTransactionId) ? rawGeneralTransactionId[0] : parseInt(rawGeneralTransactionId, 10);
            if (!Number.isInteger(generalTransactionId)) {
                throw new Error(_t("Invalid general transaction ID: ") + rawGeneralTransactionId);
            }
            console.log("General Transaction ID:", generalTransactionId);

            const transactionResults = await Promise.all(
                this.state.transactions
                    .filter(t => t.amount > 0 && t.productId)
                    .map(async trans => {
                        let model, data, result = { success: false, type: trans.type, productId: trans.productId, amount: trans.amount, name: null, error: null };
                        const receivingAccount = this.state.receivingAccounts.find(acc => acc.id === parseInt(this.state.receivingAccountId, 10));
                        const receiptAccountId = receivingAccount?.account_id || false;

                        if (!receiptAccountId) {
                            result.error = _t("Selected receiving account does not have a valid accounting account configured");
                            return result;
                        }

                        try {
                            switch (trans.type) {
                                case 'savings':
                                    model = 'savings.transaction';
                                    data = {
                                        member_id: memberId,
                                        product_id: trans.productId,
                                        amount: trans.amount,
                                        transaction_type: 'deposit',
                                        transaction_date: this.state.date,
                                        receiving_account_id: parseInt(this.state.receivingAccountId, 10),
                                        receipt_account: receiptAccountId,
                                        general_transaction_id: generalTransactionId,
                                        status: 'pending',
                                    };
                                    break;
                                case 'investments':
                                    model = 'sacco.investments.transaction';
                                    data = {
                                        member_id: memberId,
                                        product_id: trans.productId,
                                        amount: trans.amount,
                                        transaction_type: 'deposit',
                                        transaction_date: this.state.date,
                                        receiving_account_id: parseInt(this.state.receivingAccountId, 10),
                                        receipt_account: receiptAccountId,
                                        general_transaction_id: generalTransactionId,
                                        status: 'pending',
                                    };
                                    break;
                                case 'loans':
                                    model = 'sacco.loan.payments';
                                    const loanTypeId = parseInt(trans.productId, 10);
                                    const selectedLoanType = this.state.availableProducts.loans.find(lt => lt.id === loanTypeId);
                                    if (!selectedLoanType) {
                                        throw new Error(_t("Selected loan type not found"));
                                    }
                                    data = {
                                        client_id: memberId,
                                        loan_type_id: loanTypeId,
                                        amount: trans.amount,
                                        payment_date: this.state.date,
                                        receiving_account_id: parseInt(this.state.receivingAccountId, 10),
                                        receipt_account: receiptAccountId,
                                        general_transaction_id: generalTransactionId,
                                        status: 'pending',
                                    };
                                    break;
                                case 'shares':
                                    model = 'shares.transaction';
                                    data = {
                                        member_id: memberId,
                                        product_id: trans.productId,
                                        amount: trans.amount,
                                        transaction_type: 'deposit',
                                        transaction_date: this.state.date,
                                        receiving_account_id: parseInt(this.state.receivingAccountId, 10),
                                        receipt_account: receiptAccountId,
                                        general_transaction_id: generalTransactionId,
                                        status: 'pending',
                                    };
                                    break;
                                default:
                                    result.error = _t("Unknown transaction type");
                                    return result;
                            }

                            console.log(`Creating ${model} with data:`, data);
                            const rawTxId = await this.orm.create(model, [data]);
                            let txId = Array.isArray(rawTxId) ? rawTxId[0] : parseInt(rawTxId, 10);
                            if (!Number.isInteger(txId)) {
                                throw new Error(_t("Invalid transaction ID: ") + rawTxId);
                            }
                            console.log(`${model} ID:`, txId);

                            const record = await this.orm.read(model, [txId], ['name', 'amount', 'status']);
                            result.name = record[0].name;
                            result.amount = record[0].amount || 0.0;
                            result.status = record[0].status || 'N/A';
                            result.success = true;

                            await this.orm.create('sacco.transaction.link', [{
                                general_transaction_id: generalTransactionId,
                                transaction_model: model,
                                transaction_id: txId,
                                transaction_name: record[0].name,
                                transaction_amount: record[0].amount || 0.0,
                                transaction_status: record[0].status || 'N/A',
                            }]);
                        } catch (error) {
                            console.error(`Transaction failed for ${trans.type}:`, error);
                            result.error = error.message || _t("Transaction failed");
                        }
                        return result;
                    })
            );

            const generalTxRecord = await this.orm.read('sacco.general.transaction', [generalTransactionId], ['name']);
            const successfulTransactions = transactionResults.filter(t => t.success);

            if (successfulTransactions.length > 0) {
                this.state.lastTransactionSummary = {
                    memberName: this.state.memberName,
                    memberMemberID: this.state.memberMemberID,
                    date: this.state.date,
                    totalAmount: this.state.amount,
                    generalTransactionId: generalTransactionId,
                    generalTransactionName: generalTxRecord[0].name,
                    transactions: successfulTransactions.map(t => {
                        const productIdNum = parseInt(t.productId, 10);
                        const products = this.state.availableProducts[t.type] || [];
                        const product = products.find(p => p.id === productIdNum);
                        return {
                            type: t.type,
                            name: t.name,
                            productName: product ? product.name : 'Unknown',
                            amount: t.amount
                        };
                    })
                };
                this.notification.add(_t("Transactions submitted successfully and set to Verified. Awaiting approval."), { type: "success" });
            }

            const failedTransactions = transactionResults.filter(t => !t.success);
            if (failedTransactions.length > 0) {
                this.notification.add(
                    _t("Some transactions failed: ") + failedTransactions.map(t => `${t.type} - ${t.error}`).join(', '),
                    { type: "warning" }
                );
            } else if (successfulTransactions.length === 0) {
                this.notification.add(_t("No transactions were processed successfully"), { type: "danger" });
            }

            this.resetForm();

        } catch (error) {
            console.error('Error processing transactions:', error);
            this.notification.add(error.message || _t("Error processing transactions"), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    openGeneralTransaction(ev) {
        const id = ev.currentTarget.dataset.id;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'sacco.general.transaction',
            res_id: parseInt(id, 10),
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openTransaction(ev) {
        const id = ev.currentTarget.dataset.id;
        const type = ev.currentTarget.dataset.type;
        let res_model;
        switch (type) {
            case 'savings':
                res_model = 'savings.transaction';
                break;
            case 'investments':
                res_model = 'sacco.investments.transaction';
                break;
            case 'loans':
                res_model = 'sacco.loan.payments';
                break;
            case 'shares':
                res_model = 'shares.transaction';
                break;
            default:
                return;
        }
        if (this.state.availableTypes.includes(type)) {
            this.action.doAction({
                type: 'ir.actions.act_window',
                res_model: 'sacco.transaction.link',
                res_id: parseInt(id, 10),
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'current',
                context: {
                    'default_transaction_model': res_model,
                    'default_transaction_id': parseInt(id, 10),
                },
                flags: { action_buttons: true, action_open_transaction: true },
            });
        }
    }

    resetForm() {
        this.state.memberId = null;
        this.state.memberName = "";
        this.state.memberMemberID = null;
        this.state.amount = 0;
        this.state.transactions = this.state.availableTypes.length > 0 ? [{ type: this.state.availableTypes[0], productId: null, amount: 0 }] : [];
        this.state.memberSuggestions = [];
        this.state.availableProducts = { savings: [], investments: [], loans: [], shares: [] };
    }

    closeSummaryCard() {
        this.state.lastTransactionSummary = null;
    }
}

registry.category("actions").add("transactions_view", TransactionsView);