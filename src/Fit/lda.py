#!/usr/bin/env python

import numpy as np
from numpy.linalg import *
from scipy import *
from scipy.sparse.linalg import eigs
from scipy.interpolate import *
from scipy.special import *
from scipy.linalg import rq
from matplotlib import *
import matplotlib.pyplot as plt
import scipy.optimize as sciopt
from matplotlib.widgets import Slider


class LDA(object):
    def __init__(self, data):
	self.taus = np.logspace(-1, 4, 100)
        self.L = np.identity(len(self.taus))

	self.updateData(data)
	self.reg = 'L2'
	self.simfit = True #Fit all wavelengths simultaneously or individually

        #For hyperparameter selection in Elastic Net
	self.rhos = np.linspace(0.1, 0.9, 9)

    def run_LDA(self, GA_taus=None):
	if self.reg == 'L2':
	    GCVs, Cps = self._L2()
	    lcurve_x, lcurve_y, mpm_y, k = self._lcurve_MPM()
            self._plot_lcurve_MPM(lcurve_x, lcurve_y, mpm_y, k.argmax(), mpm_y.argmin())
	    self._plot_GCV_Cp(GCVs, Cps)
	elif self.reg == 'L1':
	    self._L1()
	elif self.reg == 'elnet':
	    self._elnet()
	self._plot_LDM(GA_taus)
	return

    #####################################
    # Data and Initialization Functions #
    #####################################

    # Get data and IRF parameters
    def updateData(self, data):
	self.A = data.get_data()
	self.times = data.get_T()
	self.wls = data.get_wls()
	self.irforder, self.FWHM, self.munot, self.lamnot = data.get_IRF()
        self.FWHM_mod = self.FWHM/(2*sqrt(log(2)))
	self.genD()

    # Get matrix LDA parameters
    def updateParams(self, taus, alphas, reg, L, simfit):
	self.taus = taus
	self.alphas = alphas
	self.reg = reg
	self.L = L
	self.simfit = simfit
	self.genD()
	if self.reg == 'elnet':
	    self.x_opts = np.zeros([len(self.taus), len(self.wls), len(self.alphas), len(self.rhos)])
	else:
            self.x_opts = np.zeros([len(self.taus), len(self.wls), len(self.alphas)])

    # Matrix of Exponential Decays
    def genD(self):
        D = np.zeros([len(self.times), len(self.taus)])
        for i in range(len(D)):
            for j in range(len(D[i])):
                t = self.times[i]
                tau = self.taus[j]
                One = 0.5*(exp(-t/tau)*exp((self.munot + (self.FWHM_mod**2/(2*tau)))/tau))
                Two = 1 + erf((t-(self.munot+(self.FWHM_mod**2/tau)))/(sqrt(2)*self.FWHM_mod))
                D[i, j] = One*Two
		#D[i, j] = exp(-t/tau)
	self.D = np.nan_to_num(D)

    ######################
    # Tikhonov Functions #
    ######################

    # Calculate Tikhonov solutions for all wavelengths, and all alphas
    # Runs GCV and Cp, either independently or for all wavelengths simultaneously
    def _L2(self):
	if self.simfit:
	    GCVs = np.zeros([len(self.alphas)])
            Cps = np.zeros([len(self.alphas)])
	else:
	    GCVs = np.zeros([len(self.wls), len(self.alphas)])
            Cps = np.zeros([len(self.wls), len(self.alpahs)])

	for alpha in range(len(self.alphas)):
            D_aug = np.concatenate((self.D, self.alphas[alpha]**(0.5)*self.L))
            A_aug = np.concatenate((self.A, np.zeros([len(self.L), len(self.wls)])))
	    U, S, Vt = np.linalg.svd(D_aug, full_matrices=False)
	    V = np.transpose(Vt)
	    Ut = np.transpose(U)
	    Sinv = np.diag(1/S)
	    self.x_opts[:, :, alpha] = V.dot(Sinv).dot(Ut).dot(A_aug)	    
            X = np.transpose(self.D).dot(self.D) + self.alphas[alpha]*np.transpose(self.L).dot(self.L)
            U, S, Vt = np.linalg.svd(X, full_matrices=False)
            Xinv = np.transpose(Vt).dot(np.diag(1/S)).dot(np.transpose(U))
            H = self.D.dot(Xinv).dot(np.transpose(self.D))
            if alpha == 0:
                n = len(self.times)
                self.var = sum((self.D.dot(self.x_opts[:, :, 0])-self.A)**2)/n
	    GCVs[alpha] = self._calc_GCV(alpha, H)
            Cps[alpha] = self._calc_Cp(alpha, H)
	return GCVs, Cps

    # Calculates GCV
    def _calc_GCV(self, alpha, H):
        n = len(self.times)
	I = np.identity(len(H))
	tr = (np.trace(I - H)/n)**2
	if self.simfit:
	    res = self._calc_GCV_res(alpha)
	else:
	    res = np.array([self._calc_GCV_res(alpha, wl) for wl in range(len(self.wls))])
	return res/tr

    # Calculates Cp
    def _calc_Cp(self, alpha, H, wl=None):
        n = len(self.times)
	if wl != None:
	    self.var = sum((self.D.dot(self.x_opts[:, wl, 0])-self.A[:, wl])**2)/n
	res = self._calc_res(alpha, wl)
	df = np.trace(H)
	return res + 2*self.var*df

    # Stores the L-Curve and MPM values
    def _lcurve_MPM(self):
        if self.simfit:
            lcurve_x = np.array([sqrt(self._calc_res(a)) for a in range(len(self.alphas))])
            lcurve_y = np.array([self._calc_smoothNorm(a) for a in range(len(self.alphas))])
            mpm_y = lcurve_x*lcurve_y
        else:
            lcurve_x = np.array([[self._calc_res(a, wl) for wl in range(len(self.wls))] for a in range(len(self.alphas))])
            lcurve_y = np.array([[self._calc_smoothNorm(a, wl) for wl in range(len(self.wls))] for a in range(len(self.alphas))])
            mpm_y = lcurve_x*lcurve_y
        k = self._calc_k(lcurve_x, lcurve_y)

        return lcurve_x, lcurve_y, mpm_y, k

    # Curvature function, for finding optimal alpha on L-curve
    def _calc_k(self, lx, ly):
        dx = np.gradient(lx)
        dy = np.gradient(ly, dx)
        d2y = np.gradient(dy, dx)
        k = abs(d2y)/(1+dy**2)**(1.5)#(3./2)
        return k

    # Residuals and norms
    def _calc_GCV_res(self, alpha, wl=None):
        if wl == None:
            return sum((self.D.dot(self.x_opts[:, :, alpha])-self.A)**2)
        else:
            return sum((self.D.dot(self.x_opts[:, wl, alpha])-self.A[:, wl])**2)

    def _calc_res(self, alpha, wl=None):
        if wl == None:
            return sum((self.D.dot(self.x_opts[:, :, alpha])-self.A)**2)
        else:
            return sum((self.D.dot(self.x_opts[:, wl, alpha])-self.A[:, wl])**2)

    def _calc_smoothNorm(self, alpha, wl=None):
        if wl == None:
            return sum((self.L.dot(self.x_opts[:, :, alpha]))**2)**(0.5)
        else:
            return sum((self.L.dot(self.x_opts[:, wl, alpha]))**2)**(0.5)


    ###################
    # Lasso Functions #
    ###################

    # Find LASSO for each alpha
    def _L1(self):
	G,C = self._L2()
	for i in range(len(self.alphas)):
	    alpha = self.alphas[i]
	    self.x_opts[:, :, i] = self._L1_min(self.D, self.A, alpha)

    # Does the regularized least squares after converting to orthogonal design matrix
    def _L1_min(self, D, A, alpha):
	p = len(D[0])
	#Dstd = D/sum(D**2)
	Dstd = D
	Dt = np.transpose(Dstd)
	cov = Dt.dot(Dstd)
	g, v = eigs(cov, k=1, ncv=len(D))
	I = np.identity(p)
	B = g*I - cov
	if self.reg == 'elnet':
	    x = self.x_opts[:, :, 0, 0]
	else:
	    x = self.x_opts[:, :, 0]
	cond = np.array([1])
        for j in range(len(x[0])):
            for i in range(len(x)):
                cond = np.array([1])
                while cond > 10e-12 and x[i, j] != 0: # Can change tolerance here
                    x_old = x
                    U = Dt.dot(A[:,j]) + B.dot(x_old[:,j])
                    sgn = np.sign(U[i])
                    absolute = np.absolute(U[i])
                    x_new = sgn*np.maximum((absolute-alpha)/g, 0)
                    x[i, j] = x_new[0]
                    cond = (x_new[0]-x_old[i, j])/x_old[i, j]
	return x

    # Calculate GCV
    def _L1curve(self, alpha, wl):
        #if self.simfit:
        #    l1y = np.array([sqrt(self._calc_res(a)) for a in range(len(self.alphas))])
        #    l1x = np.array([self._calc_L1Norm(a) for a in range(len(self.alphas))])
        #return l1x, l1y
        pass
    def _calc_M(self, l1x, l1y):
        pass

    def _calc_L1Norm(self, alpha, wl=None):
        if wl == None:
            return sum(abs(self.L.dot(self.x_opts[:, :, alpha])))
        else:
            return sum(abs(self.L.dot(self.x_opts[:, wl, alpha])))


    #########################
    # Elastic Net Functions #
    #########################

    # Calculate Elastic Net Solution for every alpha and rho
    # First creates augmented matrices to remove L2 penalty, reducing problem to a LASSO regularization
    def _elnet(self):
	for i in range(len(self.alphas)):
	    alpha = self.alphas[i]
	    for j in range(len(self.rhos)):
		rho = self.rhos[j]
		a1 = rho*alpha
		a2 = (1-rho)*alpha
		atil = a1/(sqrt(1+a2))

		D_aug = np.concatenate((self.D, sqrt(a2)*self.L))
		D_aug *= (1 + sqrt(a2))**(-.5)

		A_aug = np.concatenate((self.A, np.zeros([len(self.L), len(self.wls)])))

		x_naive = self._L1_min(D_aug, A_aug, atil)
		self.x_opts[:, :, i, j] = (1 + a2)*x_naive

    # Cross-validation
    def elnet_CV(self):
        pass

    ##################
    # TSVD Functions #
    ##################

    # Public function for running truncated svd regularization
    def run_tsvd(self, k, t1, t2, nt, GA_taus):
        self.taus = np.logspace(t1, t2, nt)
        self.genD()
        x = self._tsvd(k)
        fig_tsvd = plt.figure()
	fig_tsvd.canvas.set_window_title('TSVD LDM')
	max_c = np.max(np.absolute(x))
	num_c = 12
	C_pos = np.linspace(0, max_c, num_c)
	C_neg = np.linspace(-max_c, 0, num_c, endpoint=False)
	Contour_Levels = np.concatenate((C_neg, C_pos))
	ax = fig_tsvd.add_subplot(111)
        ax.contourf(self.wls, self.taus, x, cmap=plt.cm.seismic, levels=Contour_Levels)
	if GA_taus != None:
	    for i in range(len(GA_taus)):
		ax.axhline(GA_taus[i], linestyle='dashed', color='k')
	ax.set_yscale('log')
        plt.draw()

    # Actual solution
    def _tsvd(self, k):
	D_plus = self._tsvdInv(k)	
	x_k = D_plus.dot(self.A)
	return x_k

    # Truncated inverse
    def _tsvdInv(self, k):
	U, S, Vt = np.linalg.svd(self.D, full_matrices=False)
	V = np.transpose(Vt)
	Ut = np.transpose(U)
	S = 1/S
	S = np.array([S[i] if i < k else 0 for i in range(len(S))])
	S = np.diag(S)
	return V.dot(S).dot(Ut)

    # Picard condition for K selection
    def _picard(self):
        pass


    #################################
    # Output and Plotting Functions #
    #################################
    
    def display(self):
        pass

    def _plot_lcurve_MPM(self, lx, ly, my, kmax, mymin):
        fig_lcurve = plt.figure()
        fig_lcurve.canvas.set_window_title('L-Curve and MPM')
        ax = fig_lcurve.add_subplot(121)
        ax.plot(lx, ly, 'bo-')
        ax.plot(lx[kmax], ly[kmax], 'ro')
        ax.annotate(self.alphas[kmax], (lx[kmax], ly[kmax]))
        ax.set_title('L-curve')
        ax2 = fig_lcurve.add_subplot(122)
        ax2.plot(self.alphas, my, 'bo-')
        ax2.plot(self.alphas[mymin], my[mymin], 'ro')
        ax2.set_title('MPM')
        ax2.annotate(self.alphas[mymin], (self.alphas[mymin], my[mymin]))
        plt.draw()

    def _plot_GCV_Cp(self, GCVs, Cps=None):
	fig_gcv = plt.figure()
	fig_gcv.canvas.set_window_title('GCV')
	ax = fig_gcv.add_subplot(121)
	ax.plot(self.alphas, GCVs, 'bo-')
        GCVmin = GCVs.argmin()
        ax.plot(self.alphas[GCVmin], GCVs[GCVmin], 'ro')
        ax.annotate(self.alphas[GCVmin], (self.alphas[GCVmin], GCVs[GCVmin]))
        ax.set_title('GCV')

	ax2 = fig_gcv.add_subplot(122)
	ax2.plot(self.alphas, Cps, 'bo-')
        Cpmin = Cps.argmin()
        ax2.plot(self.alphas[Cpmin], Cps[Cpmin], 'ro')
        ax2.annotate(self.alphas[Cpmin], (self.alphas[Cpmin], Cps[Cpmin]))
        ax2.set_title('Cp')
	plt.draw()

    def _plot_LDM(self, GA_taus=None):
	fig_ldm = plt.figure()
	fig_ldm.canvas.set_window_title('LDM')
	ax = fig_ldm.add_subplot(121)
        #ax = fig_ldm.add_subplot(111)
	max_c = np.max(np.absolute(self.x_opts[:, :, 0]))
	if max_c > 0:
	    num_c = 20
	    C_pos = np.linspace(0, max_c, num_c)
	    C_neg = np.linspace(-max_c, 0, num_c, endpoint=False)
	    Contour_Levels = np.concatenate((C_neg, C_pos))
	else:
	    Contour_Levels = None
	if self.reg == 'elnet':
            C = ax.contourf(self.wls, self.taus, self.x_opts[:,:,0, 6], cmap=plt.cm.seismic, levels=Contour_Levels)
	else:
            C = ax.contourf(self.wls, self.taus, self.x_opts[:,:,0], cmap=plt.cm.seismic, levels=Contour_Levels)
        plt.colorbar(C)
	ax.set_yscale('log')
        ax.set_ylabel(r'$\tau$', fontsize=14)
        ax.set_xlabel('Wavelength', fontsize=14)
        ax.set_title('Alpha = %f' % self.alphas[0])
	if GA_taus != None:
	    for i in range(len(GA_taus)):
		ax.axhline(GA_taus[i], linestyle='dashed', color='k')
	ax2 = fig_ldm.add_subplot(122)
        ax2.set_title('Wavelength = %f' % self.wls[0])
        ax2.plot(self.taus, self.x_opts[:,0,0])
        ax2.set_xscale('log')
        ax2.set_xlabel(r'$\tau$', fontsize=14)
        ax2.set_ylabel('Amplitude', fontsize=14)
        ax2.yaxis.set_label_position('right')
        ax2.yaxis.tick_right()
        ax2.yaxis.label.set_rotation(270)
        for i in range(len(Contour_Levels)):
            ax2.axhline(Contour_Levels[i], linestyle='dashed', color='k')

	plt.subplots_adjust(left=0.25, bottom=0.25)
	axS = plt.axes([0.25, 0.1, 0.65, 0.03]) # Alpha slider
        axS2 = plt.axes([0.25, 0.03, 0.65, 0.03]) # Wavelength slider
        self.S = Slider(axS, 'alpha', 0, len(self.alphas), valinit=0, valfmt='%0.0f')
        self.S2 = Slider(axS2, 'Wavelength', 0, len(self.wls), valinit=0, valfmt='%0.0f')

        def update(val):
            n = int(self.S.val)
	    ax.clear()
            ax.set_title('Alpha = %f' % self.alphas[n])
	    max_c = np.max(np.absolute(self.x_opts[:, :, n]))
            if max_c > 0:
                num_c = 20
                C_pos = np.linspace(0, max_c, num_c)
                C_neg = np.linspace(-max_c, 0, num_c, endpoint=False)
                Contour_Levels = np.concatenate((C_neg, C_pos))
            else:
                Contour_Levels = None
	    if self.reg == 'elnet':
	    	C = ax.contourf(self.wls, self.taus, self.x_opts[:, :, n, 6], cmap=plt.cm.seismic, levels=Contour_Levels)
	    else:
	    	C = ax.contourf(self.wls, self.taus, self.x_opts[:, :, n], cmap=plt.cm.seismic, levels=Contour_Levels)
	    if GA_taus != None:
	        for i in range(len(GA_taus)):
		    ax.axhline(GA_taus[i], linestyle='dashed', color='k')
            plt.colorbar(C)
            ax.set_ylabel(r'$\tau$', fontsize=14)
            ax.set_xlabel('Wavelength', fontsize=14)
	    ax.set_yscale('log')

            wl = int(self.S2.val)
            ax2.clear()
            ax2.set_title('Wavelength = %f' % self.wls[wl])
            ax2.plot(self.taus, self.x_opts[:,wl,n])
            ax2.set_xscale('log')
            ax2.set_xlabel(r'$\tau$', fontsize=14)
            ax2.set_ylabel('Amplitude', fontsize=14)
            ax2.yaxis.set_label_position('right')
            ax2.yaxis.tick_right()
            ax2.yaxis.label.set_rotation(270)
            for i in range(len(Contour_Levels)):
                ax2.axhline(Contour_Levels[i], linestyle='dashed', color='k')
	    plt.draw()
        self.S.on_changed(update)
        self.S2.on_changed(update)
	plt.draw()
